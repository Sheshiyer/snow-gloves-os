"""Small authenticated, transactional fleet pilot coordinator (stdlib only)."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .fleet_business import (
    COMMERCIAL_PREPARATION_CATEGORY,
    BusinessContextError,
    inherit_business_context,
    normalize_business_context,
    validated_business_metadata,
)

ROLES = ('ceo','cto','chief-of-staff','librarian','interpreter','dispatcher','sentinel')
STAGES = ('plan','reference','review','dispatch','verify')
MAX_CHILDREN = 7
MAX_ATTEMPTS = 3  # original plus two retries per role chain
NO_NEW_CHILDREN = ('cancelled','cancel_requested','failed','interrupted')


class Rejected(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def redact(value):
    text = str(value)
    text = re.sub(r'(?i)\bbearer\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)[^\s,;]+', r'\1\2[REDACTED]', text)
    text = re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+', '[REDACTED]', text)
    return text[:16000]


class Coordinator:
    def __init__(self, config, clock=time.time):
        self.config, self.clock = config, clock
        self.root = Path(config['data_root']).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'fleet.sqlite3', check_same_thread=False)
        os.chmod(self.root / 'fleet.sqlite3', 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, project TEXT NOT NULL,
          title TEXT NOT NULL, brief TEXT NOT NULL, runtime TEXT NOT NULL,
          category TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL,
          status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
          worker TEXT, attempt_id TEXT, lease_hash TEXT, deadline REAL,
          artifact TEXT, logical_role TEXT NOT NULL DEFAULT 'cto',
          business_context TEXT, UNIQUE(owner, idem));
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
          attempt_id TEXT NOT NULL, event_id TEXT NOT NULL, type TEXT NOT NULL,
          message TEXT NOT NULL, created REAL NOT NULL,
          UNIQUE(task_id, attempt_id, event_id));
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(tasks)')}
        if 'logical_role' not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN logical_role TEXT NOT NULL DEFAULT 'cto'")
        for column in ('parent_id', 'stage', 'supersedes'):
            if column not in columns:
                self.db.execute('ALTER TABLE tasks ADD COLUMN %s TEXT' % column)
        if 'access' not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN access TEXT NOT NULL DEFAULT 'read'")
        if 'business_context' not in columns:
            self.db.execute('ALTER TABLE tasks ADD COLUMN business_context TEXT')
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_id)')
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def close(self):
        self.db.close()

    def authenticate(self, token, worker=False):
        for name, entry in self.config.get('workers' if worker else 'principals', {}).items():
            if token and hmac.compare_digest(token, entry['token']):
                return name, entry
        raise Rejected(401, 'Authentication required')

    def sanitize(self, value):
        result = redact(value)
        for group in ('principals', 'workers'):
            for entry in self.config.get(group, {}).values():
                if entry.get('token'):
                    result = result.replace(entry['token'], '[REDACTED]')
        bridge_token = self.config.get('hermes_bridge',{}).get('token')
        if bridge_token:
            result = result.replace(bridge_token,'[REDACTED]')
        return result

    def _expire(self):
        now = self.clock()
        rows = self.db.execute("SELECT id,attempt_id FROM tasks WHERE status IN ('running','cancel_requested') AND deadline < ?", (now,)).fetchall()
        for row in rows:
            self.db.execute("UPDATE tasks SET status='interrupted',updated=? WHERE id=?", (now, row['id']))
            self.db.execute('INSERT OR IGNORE INTO events(task_id,attempt_id,event_id,type,message,created) VALUES(?,?,?,?,?,?)', (row['id'],row['attempt_id'],'lease-expired','interrupted','Worker heartbeat expired; manual reconciliation required',now))

    def _context_from_row(self, row):
        raw = row['business_context']
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            raise Rejected(500, 'Stored business context is invalid') from None
        if not isinstance(value, dict):
            raise Rejected(500, 'Stored business context is invalid')
        try:
            context = normalize_business_context(value)
            self._safe_business_data(context)
            return context
        except BusinessContextError:
            raise Rejected(500, 'Stored business context is invalid') from None

    def _safe_business_data(self, value):
        encoded = json.dumps(value, sort_keys=True)
        if self.sanitize(encoded) != encoded:
            raise Rejected(400, 'Business references must not contain credentials')

    def _business_metadata(self, project, context, require_catalog_ready=True):
        try:
            result = validated_business_metadata(
                self.config['projects'][project], context,
                require_catalog_ready=require_catalog_ready,
            )
            self._safe_business_data(result[0])
            self._safe_business_data(result[2])
            return result
        except BusinessContextError as exc:
            raise Rejected(exc.status, str(exc)) from None

    def _inherit_context(self, parent_context, requested_context):
        try:
            return inherit_business_context(parent_context, requested_context)
        except BusinessContextError as exc:
            raise Rejected(exc.status, str(exc)) from None

    def _public(self, row):
        keys = ('id','owner','project','title','brief','runtime','category','status','created','updated','worker','attempt_id','logical_role','parent_id','stage','supersedes','access')
        result = {k: row[k] for k in keys}
        project = self.config['projects'][row['project']]
        result.update(tenant=project['tenant'],organization=project['organization'],session_id=row['id'])
        result['artifact'] = json.loads(row['artifact']) if row['artifact'] else None
        context = self._context_from_row(row)
        if context is not None:
            result['business_context'] = context
            try:
                self._business_metadata(row['project'], context)
                result['business_gate'] = {'dispatch_ready': True, 'erp_access': 'unverified'}
            except Rejected as exc:
                result['business_gate'] = {'dispatch_ready': False, 'erp_access': 'unverified', 'reason': str(exc.message)}
        return result

    def _owned(self, owner, principal, task_id):
        row = self.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row or row['owner'] != owner or row['project'] not in principal['projects']:
            raise Rejected(404, 'Task not found')
        return row

    def submit(self, owner, principal, body):
        project = body.get('project')
        if project not in principal['projects'] or project not in self.config['projects']:
            raise Rejected(403, 'Project unavailable')
        runtime = body.get('runtime', 'codex')
        if runtime not in self.config['projects'][project]['runtimes']:
            raise Rejected(403, 'Runtime unavailable')
        for field, limit in (('brief',16000),('idempotency_key',200)):
            if not isinstance(body.get(field),str) or not body[field].strip() or len(body[field]) > limit:
                raise Rejected(400, 'Invalid '+field)
        for field in ('title', 'category'):
            if field in body and (not isinstance(body[field],str) or len(body[field]) > 200):
                raise Rejected(400, 'Invalid '+field)
        if 'domain_role' in body:
            raise Rejected(400, 'domain_role must be supplied in business_context')
        parent_id, role, stage, supersedes = body.get('parent_id'), body.get('logical_role'), body.get('stage'), body.get('supersedes')
        if parent_id is None:
            if role is not None or stage is not None or supersedes is not None:
                raise Rejected(400, 'Role, stage and supersedes require a parent task')
        elif not isinstance(parent_id,str) or not re.fullmatch(r'[a-f0-9]{32}',parent_id):
            raise Rejected(400, 'Invalid parent_id')
        elif role not in ROLES or (stage is not None and stage not in STAGES):
            raise Rejected(400, 'Invalid logical_role or stage')
        elif supersedes is not None and (not isinstance(supersedes,str) or not re.fullmatch(r'[a-f0-9]{32}',supersedes)):
            raise Rejected(400, 'Invalid supersedes')
        access = body.get('access', 'read')
        if not isinstance(access,str) or access not in ('read','write'):
            raise Rejected(400, 'Invalid access')
        if access == 'write':
            if parent_id is None:
                raise Rejected(400, 'Write tasks must be children in a task graph')
            if role != 'cto':
                raise Rejected(403, 'Only the CTO role may write')
            if not self.config['projects'][project].get('write') or project not in principal.get('write_projects',[]):
                raise Rejected(403, 'Write access unavailable')
        marker = object()
        requested_context = body.get('business_context', marker)
        business_context, template, readiness = None, None, None
        parent_context = None
        if parent_id is not None:
            with self.lock:
                parent = self._owned(owner, principal, parent_id)
                if parent['project'] != project:
                    raise Rejected(409, 'Parent belongs to another project')
                parent_context = self._context_from_row(parent)
        if parent_id is None:
            if requested_context is not marker:
                if body.get('category') not in (None, '', COMMERCIAL_PREPARATION_CATEGORY):
                    raise Rejected(400, 'Business context requires commercial-preparation category')
                business_context, template, readiness = self._business_metadata(project, requested_context)
            elif body.get('category') == COMMERCIAL_PREPARATION_CATEGORY:
                raise Rejected(400, 'Commercial-preparation requires business context')
        elif parent_context is None:
            if requested_context is not marker or body.get('category') == COMMERCIAL_PREPARATION_CATEGORY:
                raise Rejected(409, 'Business context must originate with the parent task')
        else:
            if body.get('category') not in (None, '', COMMERCIAL_PREPARATION_CATEGORY):
                raise Rejected(409, 'Child business context must retain commercial-preparation category')
            business_context = self._inherit_context(
                parent_context,
                None if requested_context is marker else requested_context,
            )
            business_context, template, readiness = self._business_metadata(project, business_context)
        if business_context is not None and access != 'read':
            raise Rejected(403, 'Business preparation is read-only')
        request = {k: body.get(k) for k in ('project','brief','runtime','title','category')}
        if business_context is not None:
            request['category'] = COMMERCIAL_PREPARATION_CATEGORY
            request['business_context'] = business_context
        if access == 'write':
            request['access'] = access
        if parent_id is not None:
            request.update(parent_id=parent_id,logical_role=role,stage=stage)
            if supersedes is not None:
                request['supersedes'] = supersedes
        digest = hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        with self.lock:
            prior = self.db.execute('SELECT * FROM tasks WHERE owner=? AND idem=?',(owner,body['idempotency_key'])).fetchone()
            if prior:
                if prior['request_hash'] != digest:
                    raise Rejected(409, 'Idempotency key conflicts with prior request')
                return self._public(prior)
        interpretation = None
        bridge = self.config.get('hermes_bridge') if parent_id is None else None  # a parent assigns child roles; no model call
        if bridge:
            url = bridge['url'].rstrip('/')
            parsed = urlsplit(url)
            if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
                raise Rejected(503,'Hermes bridge configuration unavailable')
            request_body = {key: body.get(key) for key in ('title','brief','project','category')}
            request_body['title'] = body.get('title') or 'Fleet task'
            request_body['category'] = COMMERCIAL_PREPARATION_CATEGORY if business_context is not None else body.get('category') or 'development'
            if business_context is not None:
                request_body['business_context'] = business_context
            request = urllib.request.Request(url+'/interpret',data=json.dumps(request_body).encode(),headers={'Authorization':'Bearer '+bridge['token'],'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request,timeout=min(90,float(bridge.get('timeout',90)))) as response:
                    raw=response.read(32769)
                    if len(raw)>32768:
                        raise ValueError('Oversized response')
                    interpretation=json.loads(raw)
                if not isinstance(interpretation,dict) or interpretation.get('logical_role','cto') not in ROLES:
                    raise ValueError('Invalid role')
                for key in ('title','brief','category','summary','hermes_revision'):
                    if key in interpretation and (not isinstance(interpretation[key],str) or len(interpretation[key])>16000):
                        raise ValueError('Invalid interpretation')
                if not interpretation.get('summary') or not interpretation.get('hermes_revision'):
                    raise ValueError('Missing interpretation proof')
                if business_context is not None and (
                        interpretation.get('category') != COMMERCIAL_PREPARATION_CATEGORY
                        or interpretation.get('business_context') != business_context):
                    raise ValueError('Business scope changed')
            except (ValueError,TypeError,KeyError,urllib.error.URLError,TimeoutError,OSError):
                raise Rejected(503,'Hermes interpretation unavailable; task was not dispatched') from None
        with self.transaction():
            self._expire()
            prior = self.db.execute('SELECT * FROM tasks WHERE owner=? AND idem=?',(owner,body['idempotency_key'])).fetchone()
            if prior:
                if prior['request_hash'] != digest:
                    raise Rejected(409, 'Idempotency key conflicts with prior request')
                return self._public(prior)
            if parent_id is not None:
                parent = self._owned(owner,principal,parent_id)
                if parent['project'] != project:
                    raise Rejected(409, 'Parent belongs to another project')
                if parent['parent_id'] is not None:
                    raise Rejected(409, 'Task graphs are one level deep')
                if parent['status'] in NO_NEW_CHILDREN:
                    raise Rejected(409, 'Parent no longer accepts children')
                current_parent_context = self._context_from_row(parent)
                if current_parent_context is None and business_context is not None:
                    raise Rejected(409, 'Business context must originate with the parent task')
                if current_parent_context is not None:
                    business_context = self._inherit_context(
                        current_parent_context,
                        None if requested_context is marker else requested_context,
                    )
                    business_context, template, readiness = self._business_metadata(project, business_context)
                    if access != 'read':
                        raise Rejected(403, 'Business preparation is read-only')
                if supersedes is not None:
                    old = self._owned(owner,principal,supersedes)
                    if old['parent_id'] != parent_id or old['logical_role'] != role or old['stage'] != stage or old['access'] != access:
                        raise Rejected(409, 'A retry must match the parent, role, stage and access of the failed task')
                    if self._context_from_row(old) != business_context:
                        raise Rejected(409, 'A retry must preserve the business template and context')
                    if old['status'] != 'failed':
                        raise Rejected(409, 'Only failed tasks can be retried; interrupted tasks need manual reconciliation')
                    if self.db.execute('SELECT 1 FROM tasks WHERE supersedes=?',(supersedes,)).fetchone():
                        raise Rejected(409, 'Task was already retried')
                    attempts, cursor = 1, old
                    while cursor['supersedes']:
                        attempts, cursor = attempts + 1, self.db.execute('SELECT * FROM tasks WHERE id=?',(cursor['supersedes'],)).fetchone()
                    if attempts >= MAX_ATTEMPTS:
                        raise Rejected(409, 'Retry limit reached for this role')
                elif self.db.execute('SELECT count(*) FROM tasks WHERE parent_id=? AND id NOT IN (SELECT supersedes FROM tasks WHERE supersedes IS NOT NULL)',(parent_id,)).fetchone()[0] >= MAX_CHILDREN:
                    raise Rejected(409, 'Parent already has the maximum number of children')
            tid, now = uuid.uuid4().hex, self.clock()
            self.db.execute('INSERT INTO tasks(id,owner,project,title,brief,runtime,category,idem,request_hash,status,created,updated,business_context) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (tid,owner,project,self.sanitize(body.get('title') or 'Fleet task'),self.sanitize(body['brief']),runtime,
               self.sanitize(COMMERCIAL_PREPARATION_CATEGORY if business_context is not None else body.get('category') or 'development'),
               body['idempotency_key'],digest,'queued',now,now,
               json.dumps(business_context, sort_keys=True, separators=(',', ':')) if business_context is not None else None))
            if parent_id is not None:
                self.db.execute('UPDATE tasks SET parent_id=?,logical_role=?,stage=?,supersedes=?,access=? WHERE id=?',(parent_id,role,stage,supersedes,access,tid))
            if interpretation:
                self.db.execute('UPDATE tasks SET title=?,brief=?,category=?,logical_role=? WHERE id=?',(
                    self.sanitize(interpretation.get('title') or body.get('title') or 'Fleet task')[:200],
                    self.sanitize(interpretation.get('brief') or body['brief']),
                    self.sanitize(COMMERCIAL_PREPARATION_CATEGORY if business_context is not None else interpretation.get('category') or body.get('category') or 'development')[:200],
                    interpretation.get('logical_role','cto'),tid))
                self.db.execute('INSERT INTO events(task_id,attempt_id,event_id,type,message,created) VALUES(?,?,?,?,?,?)',
                    (tid,'','hermes-interpreted','hermes_interpreted',self.sanitize(json.dumps({'summary':interpretation['summary'],'hermes_revision':interpretation['hermes_revision']})),now))
            return self._public(self.db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())

    def list_tasks(self, owner, principal):
        with self.transaction():
            self._expire()
            return [self._public(r) for r in self.db.execute('SELECT * FROM tasks WHERE owner=? ORDER BY created DESC LIMIT 200',(owner,)) if r['project'] in principal['projects']]

    def detail(self, owner, principal, tid, events=False):
        with self.transaction():
            self._expire()
            row = self._owned(owner,principal,tid)
            if events:
                return [dict(r) for r in self.db.execute('SELECT seq,attempt_id,event_id,type,message,created FROM events WHERE task_id=? ORDER BY seq LIMIT 1000',(tid,))]
            result = self._public(row)
            if row['parent_id'] is None:
                result['graph'] = self._graph(row)
            return result

    def _graph(self, parent):
        kids = self.db.execute('SELECT * FROM tasks WHERE parent_id=? ORDER BY created',(parent['id'],)).fetchall()
        replaced = {kid['supersedes']: kid['id'] for kid in kids if kid['supersedes']}
        children = [dict({k: v for k, v in self._public(kid).items() if k in ('id','logical_role','stage','status','artifact','supersedes','business_context','business_gate')}, superseded_by=replaced.get(kid['id'])) for kid in kids]
        kids = [kid for kid in kids if kid['id'] not in replaced]  # a retried attempt no longer counts
        statuses = {kid['status'] for kid in kids}
        if not kids:
            status = 'none'
        elif statuses & {'failed','interrupted'}:
            status = 'failed'
        elif 'cancelled' in statuses or 'cancel_requested' in statuses:
            status = 'cancelled'
        elif statuses == {'succeeded'} and parent['status'] == 'succeeded' and any(kid['logical_role'] == 'sentinel' and kid['artifact'] for kid in kids):
            status = 'verified'  # derived on read: no scheduler owns this state
        else:
            status = 'incomplete'
        result = {'children': children, 'status': status}
        context = self._context_from_row(parent)
        if context is not None:
            result['business_context'] = context
        return result

    def cancel(self, owner, principal, tid):
        with self.transaction():
            self._expire()
            row = self._owned(owner,principal,tid)
            status = {'queued':'cancelled','running':'cancel_requested'}.get(row['status'],row['status'])
            now = self.clock()
            self.db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?',(status,now,tid))
            for kid in self.db.execute("SELECT id,status FROM tasks WHERE parent_id=? AND status IN ('queued','running')",(tid,)).fetchall():
                self.db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?',({'queued':'cancelled','running':'cancel_requested'}[kid['status']],now,kid['id']))
            return self._public(self._owned(owner,principal,tid))

    def claim(self, name, worker):
        with self.transaction():
            self._expire()
            active = self.db.execute("SELECT count(*) FROM tasks WHERE status IN ('running','cancel_requested')").fetchone()[0]
            if active >= min(1, int(self.config.get('capacity',1))):
                return None
            for row in self.db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created"):
                if row['project'] not in worker['projects'] or row['runtime'] not in worker['runtimes']:
                    continue
                context = self._context_from_row(row)
                template = readiness = None
                if context is not None:
                    try:
                        context, template, readiness = self._business_metadata(row['project'], context)
                    except Rejected:
                        # A changed server snapshot must never turn an already-queued
                        # price-dependent preparation into an execution permission.
                        continue
                attempt, token = uuid.uuid4().hex, uuid.uuid4().hex + uuid.uuid4().hex
                now = self.clock()
                self.db.execute("UPDATE tasks SET status='running',worker=?,attempt_id=?,lease_hash=?,deadline=?,updated=? WHERE id=?",(name,attempt,hashlib.sha256(token.encode()).hexdigest(),now+self.config.get('lease_seconds',90),now,row['id']))
                project = self.config['projects'][row['project']]
                result = self._public(self.db.execute('SELECT * FROM tasks WHERE id=?',(row['id'],)).fetchone())
                result.update(root=str(Path(project['root']).resolve()),tenant=project['tenant'],organization=project['organization'],lease_token=token,artifacts_root=str(self.artifacts))
                if context is not None:
                    result.update(
                        business_context=context,
                        business_template=template,
                        business_readiness=readiness,
                    )
                return result
            return None

    def _artifact(self, artifact):
        if not isinstance(artifact,dict) or not isinstance(artifact.get('path'),str) or not isinstance(artifact.get('sha256'),str):
            raise Rejected(400,'Invalid artifact')
        path = Path(artifact['path'])
        if not path.is_absolute():
            path = self.artifacts / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self.artifacts.resolve()) or path.is_symlink() or not resolved.is_file():
            raise Rejected(400,'Artifact outside allowed root or missing')
        if resolved.stat().st_size > 16*1024*1024:
            raise Rejected(400,'Artifact too large')
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if not hmac.compare_digest(digest,artifact['sha256']):
            raise Rejected(400,'Artifact hash mismatch')
        return {'path':str(resolved.relative_to(self.artifacts)), 'sha256':digest}

    def report(self, name, worker, body):
        for key in ('task_id','attempt_id','lease_token','event_id','type'):
            if not isinstance(body.get(key),str) or not 0 < len(body[key]) <= 200:
                raise Rejected(400,'Invalid report')
        kind = body['type']
        if kind not in ('heartbeat','log','succeeded','failed','interrupted','cancelled'):
            raise Rejected(400,'Invalid event type')
        with self.transaction():
            self._expire()
            row = self.db.execute('SELECT * FROM tasks WHERE id=?',(body['task_id'],)).fetchone()
            if not row or row['worker'] != name or row['project'] not in worker['projects'] or row['attempt_id'] != body['attempt_id'] or not hmac.compare_digest(row['lease_hash'] or '',hashlib.sha256(body['lease_token'].encode()).hexdigest()):
                raise Rejected(403,'Assignment unavailable')
            duplicate = self.db.execute('SELECT 1 FROM events WHERE task_id=? AND attempt_id=? AND event_id=?',(row['id'],row['attempt_id'],body['event_id'])).fetchone()
            if duplicate:
                return {'accepted':True,'duplicate':True,'cancel_requested':row['status']=='cancel_requested'}
            if row['status'] not in ('running','cancel_requested'):
                raise Rejected(409,'Assignment is no longer active')
            if kind == 'succeeded' and row['status'] == 'cancel_requested':
                raise Rejected(409,'Cancellation must be reconciled')
            artifact = self._artifact(body.get('artifact')) if kind == 'succeeded' else None
            message = self.sanitize(body.get('message','')).replace(body['lease_token'],'[REDACTED]')
            now = self.clock()
            self.db.execute('INSERT INTO events(task_id,attempt_id,event_id,type,message,created) VALUES(?,?,?,?,?,?)',(row['id'],row['attempt_id'],body['event_id'],kind,message,now))
            status = kind if kind in ('succeeded','failed','interrupted','cancelled') else row['status']
            self.db.execute('UPDATE tasks SET status=?,updated=?,deadline=?,artifact=COALESCE(?,artifact) WHERE id=?',(status,now,now+self.config.get('lease_seconds',90),json.dumps(artifact) if artifact else None,row['id']))
            return {'accepted':True,'duplicate':False,'cancel_requested':status=='cancel_requested'}


def load_config(path):
    path = Path(path)
    if path.stat().st_mode & 0o077:
        raise ValueError('Coordinator configuration must have mode 0600')
    config=json.loads(path.read_text())
    if not Path(config['data_root']).is_absolute():
        raise ValueError('Coordinator data root must be absolute')
    for project in config['projects'].values():
        root=Path(project['root'])
        if not root.is_absolute() or not root.is_dir() or not (root/'.git').exists():
            raise ValueError('Project roots must name existing Git repositories')
        if not all(isinstance(project.get(key),str) and project[key] for key in ('tenant','organization')) or not isinstance(project.get('runtimes'),list):
            raise ValueError('Invalid project configuration')
    tokens=set()
    for group in ('principals','workers'):
        for entry in config[group].values():
            token=entry.get('token')
            if not isinstance(token,str) or len(token)<16 or token in tokens:
                raise ValueError('Credentials must be unique nonempty strings of at least 16 characters')
            tokens.add(token)
            if not isinstance(entry.get('projects'),list) or any(project not in config['projects'] for project in entry['projects']):
                raise ValueError('Invalid credential project scope')
            if group=='workers' and not isinstance(entry.get('runtimes'),list):
                raise ValueError('Invalid worker runtime scope')
    config['capacity']=1
    return config


def server(coordinator, port=4101):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'SnowGlovesFleet/1'
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.handle_request()
        def do_POST(self):
            self.handle_request()
        def do_OPTIONS(self):
            origin=self.headers.get('Origin')
            host=self.headers.get('Host')
            if len(self.headers.get_all('Origin',[]))!=1 or len(self.headers.get_all('Host',[]))!=1 or origin not in coordinator.config.get('allowed_origins',[]) or host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                return self.send_json(403,{'error':'Origin or host unavailable'})
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Access-Control-Allow-Methods','GET, POST')
            self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
            self.send_header('Vary','Origin')
            self.send_header('Content-Length','0')
            self.end_headers()
        def handle_request(self):
            try:
                self.connection.settimeout(5)
                for header in ('Host','Authorization','Content-Length','Origin','Content-Type'):
                    if len(self.headers.get_all(header,[])) > 1:
                        raise Rejected(400,'Duplicate header')
                host = self.headers.get('Host','')
                if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                    raise Rejected(403,'Host unavailable')
                origin = self.headers.get('Origin')
                if origin and origin not in coordinator.config.get('allowed_origins',[]):
                    raise Rejected(403,'Origin unavailable')
                if self.headers.get('Transfer-Encoding'):
                    raise Rejected(400,'Transfer encoding unsupported')
                parsed = urlsplit(self.path)
                if parsed.query or parsed.fragment or len(self.path)>300:
                    raise Rejected(400,'Invalid path')
                path = parsed.path
                if self.command=='GET' and path=='/healthz':
                    return self.send_json(200,{'ok':True,'service':'snow-gloves-coordinator'})
                auth = self.headers.get('Authorization','')
                token = auth[7:] if auth.startswith('Bearer ') else ''
                worker_route = path.startswith('/v1/worker/')
                name, principal = coordinator.authenticate(token,worker=worker_route)
                body = {}
                if self.command == 'POST':
                    if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                        raise Rejected(415,'JSON required')
                    length = int(self.headers.get('Content-Length','0'))
                    if not 0 < length <= 32768:
                        raise Rejected(413,'Invalid body size')
                    def pairs(items):
                        result = {}
                        for key,value in items:
                            if key in result:
                                raise Rejected(400,'Duplicate JSON key')
                            result[key]=value
                        return result
                    body = json.loads(self.rfile.read(length),object_pairs_hook=pairs)
                    if not isinstance(body,dict):
                        raise Rejected(400,'Object required')
                if path=='/v1/worker/claim' and self.command=='POST':
                    result={'task':coordinator.claim(name,principal)}
                elif path=='/v1/worker/report' and self.command=='POST':
                    result=coordinator.report(name,principal,body)
                elif path=='/v1/tasks' and self.command=='GET':
                    result={'tasks':coordinator.list_tasks(name,principal)}
                elif path=='/v1/tasks' and self.command=='POST':
                    result=coordinator.submit(name,principal,body)
                elif not worker_route and re.fullmatch(r'/v1/tasks/[a-f0-9]{32}(?:/(?:events|cancel))?',path):
                    parts=path.split('/')
                    if self.command=='POST' and len(parts)==5 and parts[4]=='cancel':
                        result=coordinator.cancel(name,principal,parts[3])
                    elif self.command=='GET' and (len(parts)==4 or parts[4]=='events'):
                        result=coordinator.detail(name,principal,parts[3],events=len(parts)==5)
                        if len(parts)==5:
                            result={'events':result}
                    else:
                        raise Rejected(405,'Method unavailable')
                else:
                    raise Rejected(404,'Route unavailable')
                self.send_json(200,result)
            except Rejected as exc:
                self.send_json(exc.status,{'error':exc.message})
            except (ValueError,TypeError,KeyError):
                self.send_json(400,{'error':'Invalid request'})
            except Exception:
                self.send_json(500,{'error':'Coordinator operation failed'})
        def send_json(self,status,result):
            payload=json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            origin=self.headers.get('Origin')
            if origin in coordinator.config.get('allowed_origins',[]):
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin')
            self.end_headers()
            self.wfile.write(payload)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)
