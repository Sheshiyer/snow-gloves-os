"""Small authenticated, transactional fleet pilot coordinator (stdlib only)."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lib.fleet_business import (
    COMMERCIAL_PREPARATION_CATEGORY,
    BusinessContextError,
    inherit_business_context,
    normalize_business_context,
    validated_business_metadata,
)
from lib.fleet_write_review import MAX_ARTIFACT_BYTES, ReviewEvidenceError, evidence_from_artifact


ROLES = ('ceo','cto','chief-of-staff','librarian','interpreter','dispatcher','sentinel')
STAGES = ('plan','reference','review','dispatch','verify')
MAX_CHILDREN = 7
PERMISSIONS = ('read','submit','cancel')  # legacy defaults never grant approval authority
VALID_PERMISSIONS = (*PERMISSIONS, 'approve')
MAX_ATTEMPTS = 3  # original plus two retries per role chain
NO_NEW_CHILDREN = ('cancelled','cancel_requested','failed','interrupted')
MAX_HTTP_BODY_BYTES = 64 * 1024
MAX_REMOTE_ARTIFACT_BYTES = 24 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 4096
NODE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')
NO_FANOUT_ROOTS = ('cancelled','cancel_requested','failed','interrupted')
MAX_FANOUT_TITLE = 200
MAX_FANOUT_BRIEF = 4000
# A source result is task data, not an artifact transfer.  Keep each delivered
# output small enough for a bounded read-only prompt; the fanout count already
# bounds the aggregate to seven such values.
MAX_SOURCE_OUTPUT_BYTES = 4096
FANOUT_ACTION_REASONS = {
    'Submit unavailable': 'Read-only role planning is not permitted for this account.',
    'Task not found': 'Read-only role planning is unavailable for this task.',
    'Fanout unavailable': 'Read-only role planning is not enabled for this task.',
    'Only root tasks can be fanned out': 'Only root tasks can plan read-only roles.',
    'Only development tasks can be fanned out': 'Only development tasks can plan read-only roles.',
    'Root no longer accepts automatic children': 'This task no longer accepts read-only role planning.',
    'Manual children prevent automatic fanout': 'Manual children already exist, so read-only roles cannot be planned.',
}


class Rejected(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Rejected(400, 'Duplicate JSON key')
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError('Invalid JSON constant: ' + value)


def _validate_json(value, depth=0, count=None):
    """Reject pathological or non-UTF-8 JSON before it reaches durable state."""
    count = [0] if count is None else count
    if depth > MAX_JSON_DEPTH:
        raise ValueError('JSON is too deeply nested')
    count[0] += 1
    if count[0] > MAX_JSON_ITEMS:
        raise ValueError('JSON has too many values')
    if isinstance(value, str):
        value.encode('utf-8')
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('JSON number is not finite')
    elif isinstance(value, list):
        for item in value:
            _validate_json(item, depth + 1, count)
    elif isinstance(value, dict):
        for key, item in value.items():
            key.encode('utf-8')
            _validate_json(item, depth + 1, count)


def _bounded_json_object(raw, limit, size_message='Invalid body size'):
    """Decode one small JSON object with duplicate, depth, and UTF-8 checks."""
    if not isinstance(raw, (bytes, bytearray)) or not 0 < len(raw) <= limit:
        raise Rejected(413, size_message)
    try:
        value = json.loads(bytes(raw).decode('utf-8'), object_pairs_hook=_unique_pairs,
                           parse_constant=_reject_json_constant)
        _validate_json(value)
    except Rejected:
        raise
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        raise Rejected(400, 'Invalid JSON') from None
    if not isinstance(value, dict):
        raise Rejected(400, 'Object required')
    return value


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


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
        CREATE TABLE IF NOT EXISTS fanout_plans (
          id TEXT PRIMARY KEY, root_id TEXT NOT NULL UNIQUE,
          owner TEXT NOT NULL, project TEXT NOT NULL, plan_json TEXT NOT NULL,
          created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS fanout_children (
          plan_id TEXT NOT NULL, task_id TEXT NOT NULL UNIQUE,
          ordinal INTEGER NOT NULL, logical_role TEXT NOT NULL, stage TEXT NOT NULL,
          PRIMARY KEY(plan_id, ordinal), UNIQUE(plan_id, logical_role));
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(tasks)')}
        if 'logical_role' not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN logical_role TEXT NOT NULL DEFAULT 'cto'")
        for column in ('parent_id', 'stage', 'supersedes'):
            if column not in columns:
                self.db.execute('ALTER TABLE tasks ADD COLUMN %s TEXT' % column)
        if 'access' not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN access TEXT NOT NULL DEFAULT 'read'")
        for column in ('review_of', 'review_binding'):
            if column not in columns:
                self.db.execute('ALTER TABLE tasks ADD COLUMN %s TEXT' % column)
        if 'business_context' not in columns:
            self.db.execute('ALTER TABLE tasks ADD COLUMN business_context TEXT')
        self.db.execute('CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_id)')
        self.db.execute('CREATE INDEX IF NOT EXISTS fanout_children_task ON fanout_children(task_id)')
        if 'requested_worker' not in columns:
            self.db.execute('ALTER TABLE tasks ADD COLUMN requested_worker TEXT')
        from .fleet_capabilities import Capabilities, install
        install(self)
        self.capabilities = Capabilities(self)
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
        keys = ('id','owner','project','title','brief','runtime','category','status','created','updated','worker','attempt_id','logical_role','parent_id','stage','supersedes','access','review_of','requested_worker')
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

    @staticmethod
    def _need(principal, permission):
        if permission not in principal.get('permissions', PERMISSIONS):
            raise Rejected(403, permission.capitalize() + ' unavailable')

    def _owned(self, owner, principal, task_id, mutate=False):
        """Fetch a task the principal may see; mutations stay with the owner, viewing may be granted via view_owners."""
        row = self.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        owners = {owner} if mutate else {owner, *principal.get('view_owners', [])}
        if not row or row['owner'] not in owners or row['project'] not in principal['projects']:
            raise Rejected(404, 'Task not found')
        return row

    def _fanout_allowed(self, principal, project):
        grants = principal.get('fanout_projects', [])
        if (self.config['projects'][project].get('fanout') is not True
                or not isinstance(grants, list) or project not in grants):
            raise Rejected(403, 'Fanout unavailable')

    def _fanout_preflight(self, owner, principal, root_id):
        # Planning creates children. It must therefore use the same submit
        # permission and owner-only mutation boundary as task submission,
        # rather than the broader read/view_owners boundary used for detail.
        self._need(principal, 'submit')
        root = self._owned(owner, principal, root_id, mutate=True)
        self._fanout_allowed(principal, root['project'])
        plan = self.db.execute('SELECT * FROM fanout_plans WHERE root_id=?', (root_id,)).fetchone()
        if plan:
            return root, plan
        if root['parent_id'] is not None:
            raise Rejected(409, 'Only root tasks can be fanned out')
        if root['category'] != 'development':
            raise Rejected(409, 'Only development tasks can be fanned out')
        if root['status'] in NO_FANOUT_ROOTS:
            raise Rejected(409, 'Root no longer accepts automatic children')
        if self.db.execute('SELECT 1 FROM tasks WHERE parent_id=? LIMIT 1', (root_id,)).fetchone():
            raise Rejected(409, 'Manual children prevent automatic fanout')
        return root, None

    def _fanout_action(self, owner, principal, root):
        """Derive a display-only admission contract from the same preflight as POST.

        This never accepts authority from the browser.  A caller can see that a
        durable plan exists even when a current grant no longer allows replay,
        but `available` stays false unless the exact POST preflight passes.
        """
        planned = bool(self.db.execute(
            'SELECT 1 FROM fanout_plans WHERE root_id=?', (root['id'],)
        ).fetchone())
        try:
            _, plan = self._fanout_preflight(owner, principal, root['id'])
        except Rejected as error:
            return {
                'available': False,
                'planned': planned,
                'reason': FANOUT_ACTION_REASONS.get(
                    error.message, 'Read-only role planning is unavailable for this task.'
                ),
            }
        if plan:
            return {
                'available': False,
                'planned': True,
                'reason': 'Read-only roles are already planned for this task.',
            }
        return {
            'available': True,
            'planned': False,
            'reason': 'Read-only roles can be planned for this task.',
        }

    def _validate_fanout_plan(self, value):
        if not isinstance(value, dict) or set(value) != {'children'} or not isinstance(value['children'], list):
            raise ValueError('Invalid plan shape')
        children = value['children']
        if not 2 <= len(children) <= MAX_CHILDREN:
            raise ValueError('Invalid child count')
        roles = set()
        normalized = []
        for child in children:
            if not isinstance(child, dict) or set(child) != {'logical_role', 'stage', 'title', 'brief'}:
                raise ValueError('Invalid child shape')
            role, stage = child['logical_role'], child['stage']
            title, brief = child['title'], child['brief']
            if role not in ROLES or role in roles or stage not in STAGES:
                raise ValueError('Invalid child assignment')
            if (not isinstance(title, str) or not title.strip() or len(title) > MAX_FANOUT_TITLE
                    or not isinstance(brief, str) or not brief.strip() or len(brief) > MAX_FANOUT_BRIEF):
                raise ValueError('Invalid child content')
            roles.add(role)
            normalized.append(dict(logical_role=role, stage=stage, title=title, brief=brief))
        if 'sentinel' not in roles or children[-1]['logical_role'] != 'sentinel' or children[-1]['stage'] != 'verify':
            raise ValueError('Sentinel must be the final verify child')
        return normalized

    def _plan_from_hermes(self, root):
        bridge = self.config.get('hermes_bridge')
        if not isinstance(bridge, dict):
            raise Rejected(503, 'Hermes plan unavailable; no children created')
        raw_url = bridge.get('url')
        if not isinstance(raw_url, str):
            raise Rejected(503, 'Hermes bridge configuration unavailable')
        url = raw_url.rstrip('/')
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
                or not isinstance(bridge.get('token'), str) or not bridge['token']):
            raise Rejected(503, 'Hermes bridge configuration unavailable')
        body = {'brief': self.sanitize(root['brief']), 'roles': list(ROLES), 'stages': list(STAGES)}
        request = urllib.request.Request(url + '/plan', data=json.dumps(body).encode(),
                                         headers={'Authorization': 'Bearer ' + bridge['token'],
                                                  'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=min(90, float(bridge.get('timeout', 90)))) as response:
                raw = response.read(32769)
                if len(raw) > 32768:
                    raise ValueError('Oversized response')
                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result:
                            raise ValueError('Duplicate JSON key')
                        result[key] = value
                    return result
                return json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, TypeError, KeyError, urllib.error.URLError, TimeoutError, OSError):
            raise Rejected(503, 'Hermes plan unavailable; no children created') from None

    def _fanout_response(self, plan):
        rows = self.db.execute('''
          SELECT tasks.*, fanout_children.ordinal
          FROM fanout_children JOIN tasks ON tasks.id=fanout_children.task_id
          WHERE fanout_children.plan_id=?
          ORDER BY fanout_children.ordinal
        ''', (plan['id'],)).fetchall()
        children = []
        for row in rows:
            children.append({
                'id': row['id'], 'parent_id': row['parent_id'], 'owner': row['owner'],
                'project': row['project'], 'runtime': row['runtime'], 'category': row['category'],
                'title': row['title'], 'brief': row['brief'], 'logical_role': row['logical_role'],
                'stage': row['stage'], 'access': row['access'], 'status': row['status'],
                'order': row['ordinal'] + 1,
            })
        return {'plan_id': plan['id'], 'root_id': plan['root_id'], 'children': children}

    def fanout(self, owner, principal, root_id, body=None):
        if body not in (None, {}):
            raise Rejected(400, 'Fanout accepts no options')
        if not isinstance(root_id, str) or not re.fullmatch(r'[a-f0-9]{32}', root_id):
            raise Rejected(400, 'Invalid task id')
        # Finish every authorization and scope gate before Hermes is ever contacted.
        with self.transaction():
            self._expire()
            root, existing = self._fanout_preflight(owner, principal, root_id)
            if existing:
                return self._fanout_response(existing)
            authorized_brief = self.sanitize(root['brief'])
        try:
            children = self._validate_fanout_plan(self._plan_from_hermes(
                {'brief': authorized_brief}))
        except ValueError:
            raise Rejected(503, 'Hermes plan unavailable or invalid; no children created') from None
        normalized = [
            dict(logical_role=child['logical_role'], stage=child['stage'],
                 title=self.sanitize(child['title'])[:MAX_FANOUT_TITLE],
                 brief=self.sanitize(child['brief'])[:MAX_FANOUT_BRIEF])
            for child in children
        ]
        plan_id = uuid.uuid4().hex
        with self.transaction():
            self._expire()
            root, existing = self._fanout_preflight(owner, principal, root_id)
            if existing:
                return self._fanout_response(existing)
            now = self.clock()
            plan = {'children': normalized}
            self.db.execute('INSERT INTO fanout_plans(id,root_id,owner,project,plan_json,created) VALUES(?,?,?,?,?,?)',
                            (plan_id, root['id'], root['owner'], root['project'],
                             json.dumps(plan, sort_keys=True, separators=(',', ':')), now))
            assignments = []
            for ordinal, child in enumerate(normalized):
                task_id = uuid.uuid4().hex
                request = {
                    'parent_id': root['id'], 'logical_role': child['logical_role'], 'stage': child['stage'],
                    'project': root['project'], 'runtime': root['runtime'], 'title': child['title'],
                    'brief': child['brief'], 'category': 'development', 'access': 'read',
                }
                self.db.execute('''
                  INSERT INTO tasks(
                    id,owner,project,title,brief,runtime,category,idem,request_hash,status,created,updated,
                    logical_role,parent_id,stage,access
                  ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (task_id, root['owner'], root['project'], child['title'], child['brief'], root['runtime'],
                      'development', 'fanout:%s:%d' % (plan_id, ordinal),
                      hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
                      'queued', now, now, child['logical_role'], root['id'], child['stage'], 'read'))
                self.db.execute('INSERT INTO fanout_children(plan_id,task_id,ordinal,logical_role,stage) VALUES(?,?,?,?,?)',
                                (plan_id, task_id, ordinal, child['logical_role'], child['stage']))
                assignments.append({'id': task_id, 'logical_role': child['logical_role'], 'stage': child['stage']})
            audit = {'root_id': root['id'], 'plan_id': plan_id, 'children': assignments}
            self.db.execute('INSERT INTO events(task_id,attempt_id,event_id,type,message,created) VALUES(?,?,?,?,?,?)',
                            (root['id'], '', 'chief-of-staff-plan:' + plan_id,
                             'chief_of_staff_plan_accepted',
                             self.sanitize(json.dumps(audit, separators=(',', ':'))), now))
            plan_row = self.db.execute('SELECT * FROM fanout_plans WHERE id=?', (plan_id,)).fetchone()
            return self._fanout_response(plan_row)

    def _fanout_membership(self, row):
        """Return the immutable plan membership for an initial child or its retry."""
        base, seen = row, set()
        while base['supersedes']:
            if base['id'] in seen:
                return None
            seen.add(base['id'])
            base = self.db.execute('SELECT * FROM tasks WHERE id=?', (base['supersedes'],)).fetchone()
            if not base:
                return None
        member = self.db.execute('SELECT * FROM fanout_children WHERE task_id=?', (base['id'],)).fetchone()
        if not member:
            return None
        plan = self.db.execute('SELECT * FROM fanout_plans WHERE id=?', (member['plan_id'],)).fetchone()
        if not plan:
            return None
        return plan, member

    def _latest_attempt(self, row):
        """A planned child may retain the existing bounded retry semantics."""
        current, seen = row, set()
        while True:
            if current['id'] in seen:
                return None
            seen.add(current['id'])
            successor = self.db.execute('SELECT * FROM tasks WHERE supersedes=?', (current['id'],)).fetchone()
            if not successor:
                return current
            current = successor

    def _source_reference(self, row, owner, project, include_output=False):
        """Recheck a completed source and optionally extract its bounded output.

        The returned output is derived from the exact bytes whose digest was
        rechecked here.  It is never an artifact envelope or a path the worker
        should resolve.  The final value class lets fanout expose a safe,
        actionable dependency hold without disclosing artifact contents.
        """
        if (not row or row['owner'] != owner or row['project'] != project
                or not isinstance(row['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', row['id'])
                or not isinstance(row['attempt_id'], str)
                or not re.fullmatch(r'[a-f0-9]{32}', row['attempt_id'])):
            return None, None, 'artifact'
        try:
            artifact = json.loads(row['artifact']) if row['artifact'] else None
            verified, payload = self._artifact_payload(artifact)

            def unique_pairs(items):
                envelope = {}
                for key, value in items:
                    if key in envelope:
                        raise ValueError('Duplicate artifact envelope key')
                    envelope[key] = value
                return envelope

            def invalid_constant(_value):
                raise ValueError('Invalid artifact envelope constant')

            envelope = json.loads(payload, object_pairs_hook=unique_pairs,
                                  parse_constant=invalid_constant)
            if (not isinstance(envelope, dict)
                    or envelope.get('task_id') != row['id']
                    or envelope.get('attempt_id') != row['attempt_id']):
                return None, None, 'artifact'
            source_output = None
            if include_output:
                output = envelope.get('output')
                if not isinstance(output, str) or not output.strip():
                    return None, None, 'output'
                try:
                    if len(output.encode('utf-8')) > MAX_SOURCE_OUTPUT_BYTES:
                        return None, None, 'output'
                except UnicodeError:
                    return None, None, 'output'
                # Coordinator credentials never cross from a predecessor
                # artifact into a child claim.  This is intentionally done
                # after validation so redaction cannot make malformed content
                # look valid.
                output = self.sanitize(output)
                try:
                    if not output.strip() or len(output.encode('utf-8')) > MAX_SOURCE_OUTPUT_BYTES:
                        return None, None, 'output'
                except UnicodeError:
                    return None, None, 'output'
                source_output = {
                    'task_id': row['id'],
                    'attempt_id': row['attempt_id'],
                    'output': output,
                }
        except (OSError, Rejected, TypeError, ValueError, RecursionError, UnicodeError):
            return None, None, 'artifact'
        return {'task_id': row['id'], 'artifact': verified}, source_output, None

    def _review_secrets(self):
        values = []
        for group in ('principals', 'workers'):
            values.extend(entry.get('token') for entry in self.config.get(group, {}).values())
        bridge = self.config.get('hermes_bridge', {})
        values.append(bridge.get('token') if isinstance(bridge, dict) else None)
        return tuple(value for value in values if isinstance(value, str) and value)

    def _review_binding_for_submission(self, owner, project, parent_id, source_id):
        """Freeze one succeeded CTO write attempt and its verified artifact digest."""
        if self.config['projects'][project].get('write_review_context') is not True:
            raise Rejected(403, 'Write review context unavailable')
        source = self.db.execute('SELECT * FROM tasks WHERE id=?', (source_id,)).fetchone()
        root = self.db.execute('SELECT * FROM tasks WHERE id=?', (parent_id,)).fetchone()
        if (not source or not root or source['owner'] != owner or root['owner'] != owner
                or source['project'] != project or root['project'] != project
                or source['parent_id'] != parent_id or root['parent_id'] is not None
                or source['status'] != 'succeeded' or source['logical_role'] != 'cto'
                or source['access'] != 'write' or source['category'] != 'development'
                or source['runtime'] != 'codex' or not isinstance(source['attempt_id'], str)
                or not re.fullmatch(r'[a-f0-9]{32}', source['attempt_id'])
                or self.db.execute('SELECT 1 FROM tasks WHERE supersedes=? LIMIT 1', (source_id,)).fetchone()):
            raise Rejected(409, 'Write review source unavailable')
        try:
            artifact, payload = self._artifact_payload(json.loads(source['artifact']) if source['artifact'] else None,
                                                       max_bytes=MAX_ARTIFACT_BYTES)
            evidence_from_artifact(payload, source['id'], source['attempt_id'], artifact['sha256'],
                                   self._review_secrets())
        except (Rejected, TypeError, ValueError, OSError, RecursionError, ReviewEvidenceError):
            raise Rejected(409, 'Write review source unavailable') from None
        return {'task_id': source['id'], 'attempt_id': source['attempt_id'],
                'artifact_sha256': artifact['sha256']}

    def _review_context(self, row):
        """Revalidate frozen review provenance at claim and return safe evidence or a generic hold."""
        if row['review_of'] is None:
            if row['review_binding'] is not None:
                return None, 'Review held: source or authorization checks require reconciliation.'
            return None, None
        hold = 'Review held: source or authorization checks require reconciliation.'
        owner = row['owner']
        principal = self.config.get('principals', {}).get(owner)
        project = self.config.get('projects', {}).get(row['project'])
        if (not principal or 'read' not in principal.get('permissions', PERMISSIONS)
                or row['project'] not in principal.get('projects', []) or not project
                or project.get('write_review_context') is not True):
            return None, hold
        if (row['access'] != 'read' or row['logical_role'] != 'sentinel' or row['stage'] != 'verify'
                or row['runtime'] != 'codex' or row['category'] != 'development'
                or not isinstance(row['parent_id'], str)):
            return None, hold
        try:
            if not isinstance(row['review_binding'], str) or len(row['review_binding']) > 4096:
                return None, hold
            def unique_pairs(items):
                out = {}
                for key, value in items:
                    if key in out:
                        raise ValueError('duplicate binding key')
                    out[key] = value
                return out
            binding = json.loads(row['review_binding'], object_pairs_hook=unique_pairs,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if (not isinstance(binding, dict) or set(binding) != {'task_id', 'attempt_id', 'artifact_sha256'}
                    or binding['task_id'] != row['review_of']
                    or not isinstance(binding['attempt_id'], str)
                    or not re.fullmatch(r'[a-f0-9]{32}', binding['attempt_id'])
                    or not isinstance(binding['artifact_sha256'], str)
                    or not re.fullmatch(r'[a-f0-9]{64}', binding['artifact_sha256'])):
                return None, hold
            source = self.db.execute('SELECT * FROM tasks WHERE id=?', (row['review_of'],)).fetchone()
            root = self.db.execute('SELECT * FROM tasks WHERE id=?', (row['parent_id'],)).fetchone()
            if (not source or not root or source['owner'] != owner or root['owner'] != owner
                    or source['project'] != row['project'] or root['project'] != row['project']
                    or source['parent_id'] != row['parent_id'] or root['parent_id'] is not None
                    or root['status'] in NO_NEW_CHILDREN
                    or source['status'] != 'succeeded' or source['logical_role'] != 'cto'
                    or source['access'] != 'write' or source['category'] != 'development'
                    or source['runtime'] != 'codex' or source['attempt_id'] != binding['attempt_id']
                    or self.db.execute('SELECT 1 FROM tasks WHERE supersedes=? LIMIT 1', (source['id'],)).fetchone()):
                return None, hold
            artifact, payload = self._artifact_payload(json.loads(source['artifact']) if source['artifact'] else None,
                                                       max_bytes=MAX_ARTIFACT_BYTES)
            if artifact['sha256'] != binding['artifact_sha256']:
                return None, hold
            evidence = evidence_from_artifact(payload, source['id'], source['attempt_id'],
                                              artifact['sha256'], self._review_secrets())
            return evidence, None
        except (Rejected, TypeError, ValueError, OSError, RecursionError, ReviewEvidenceError):
            return None, hold

    def _review_hold(self, row):
        if row['review_of'] is None:
            return None
        return self._review_context(row)[1]

    def _fanout_context(self, row):
        """Derive a planned child's dependency hold and safe immutable inputs."""
        membership = self._fanout_membership(row)
        if not membership:
            return None
        plan, member = membership
        root = self.db.execute('SELECT * FROM tasks WHERE id=?', (plan['root_id'],)).fetchone()
        base = {'plan_id': plan['id'], 'order': member['ordinal'] + 1}
        include_outputs = self.config['projects'][row['project']].get('artifact_context') is True
        if (not root or root['owner'] != row['owner'] or root['project'] != row['project']
                or root['parent_id'] is not None):
            return dict(base, hold_reason='Blocked: automatic plan context is unavailable')
        if include_outputs and row['access'] != 'read':
            return dict(base, hold_reason='Blocked: source context requires automatic read-only access')
        if root['status'] != 'succeeded':
            state = root['status']
            if state in NO_FANOUT_ROOTS:
                return dict(base, hold_reason='Blocked: parent %s is %s' % (root['id'], state))
            return dict(base, hold_reason='Waiting: parent %s must succeed' % root['id'])
        root_source, root_output, root_failure = self._source_reference(
            root, row['owner'], row['project'], include_outputs)
        if not root_source:
            suffix = 'artifact output context check failed' if root_failure == 'output' else 'artifact integrity check failed'
            return dict(base, hold_reason='Blocked: parent %s' % suffix)
        sources = [root_source]
        outputs = [root_output] if include_outputs else []
        predecessors = self.db.execute('''
          SELECT tasks.*
          FROM fanout_children JOIN tasks ON tasks.id=fanout_children.task_id
          WHERE fanout_children.plan_id=? AND fanout_children.ordinal<?
          ORDER BY fanout_children.ordinal
        ''', (plan['id'], member['ordinal'])).fetchall()
        for predecessor in predecessors:
            effective = self._latest_attempt(predecessor)
            if not effective:
                return dict(base, hold_reason='Blocked: planned predecessor is unavailable')
            if effective['status'] != 'succeeded':
                state = effective['status']
                label = '%s (%s)' % (effective['id'], predecessor['logical_role'])
                if state in NO_NEW_CHILDREN:
                    return dict(base, hold_reason='Blocked: planned predecessor %s is %s' % (label, state))
                return dict(base, hold_reason='Waiting: planned predecessor %s must succeed' % label)
            if include_outputs and effective['access'] != 'read':
                return dict(base, hold_reason='Blocked: predecessor source context requires read-only access')
            source, source_output, failure = self._source_reference(
                effective, row['owner'], row['project'], include_outputs)
            if not source:
                suffix = 'artifact output context check failed' if failure == 'output' else 'artifact integrity check failed'
                return dict(base, hold_reason='Blocked: predecessor %s' % suffix)
            sources.append(source)
            if include_outputs:
                outputs.append(source_output)
        result = dict(base, source_artifacts=sources)
        if include_outputs:
            result['source_outputs'] = outputs
        return result

    def submit(self, owner, principal, body):
        self._need(principal, 'submit')
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
        review_of = body.get('review_of')
        review_binding = None
        if review_of is not None:
            if not isinstance(review_of, str) or not re.fullmatch(r'[a-f0-9]{32}', review_of):
                raise Rejected(400, 'Invalid review_of')
            self._need(principal, 'read')
            if (parent_id is None or role != 'sentinel' or stage != 'verify' or access != 'read'
                    or runtime != 'codex' or body.get('category', 'development') != 'development'):
                raise Rejected(400, 'Write review requires a read-only Sentinel verify child')
            review_binding = self._review_binding_for_submission(owner, project, parent_id, review_of)
        elif 'review_of' in body:
            raise Rejected(400, 'Invalid review_of')
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
                parent = self._owned(owner, principal, parent_id, mutate=True)
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
        if business_context is not None and review_of is not None:
            raise Rejected(409, 'Write review is unavailable for business preparation')
        worker_id = body.get('worker_id')
        if worker_id is not None:
            if not isinstance(worker_id, str) or worker_id not in [worker['id'] for worker in self.capabilities.workers(project, runtime, access)]:
                raise Rejected(403, 'Selected worker unavailable')
        request = {k: body.get(k) for k in ('project','brief','runtime','title','category')}
        if business_context is not None:
            request['category'] = COMMERCIAL_PREPARATION_CATEGORY
            request['business_context'] = business_context
        if worker_id is not None:
            request['worker_id'] = worker_id
        if access == 'write':
            request['access'] = access
        if parent_id is not None:
            request.update(parent_id=parent_id,logical_role=role,stage=stage)
            if supersedes is not None:
                request['supersedes'] = supersedes
        if review_of is not None:
            request.update(review_of=review_of, review_binding=review_binding)
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
                parent = self._owned(owner,principal,parent_id,mutate=True)
                if parent['project'] != project:
                    raise Rejected(409, 'Parent belongs to another project')
                if parent['parent_id'] is not None:
                    raise Rejected(409, 'Task graphs are one level deep')
                if parent['status'] in NO_NEW_CHILDREN:
                    raise Rejected(409, 'Parent no longer accepts children')
                plan = self.db.execute(
                    'SELECT * FROM fanout_plans WHERE root_id=?', (parent_id,)
                ).fetchone()
                if plan and supersedes is None:
                    raise Rejected(409, 'Automatic fanout plans accept retries only')
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
                    old = self._owned(owner,principal,supersedes,mutate=True)
                    if old['parent_id'] != parent_id or old['logical_role'] != role or old['stage'] != stage or old['access'] != access:
                        raise Rejected(409, 'A retry must match the parent, role, stage and access of the failed task')
                    if self._context_from_row(old) != business_context:
                        raise Rejected(409, 'A retry must preserve the business template and context')
                    if old['status'] != 'failed':
                        raise Rejected(409, 'Only failed tasks can be retried; interrupted tasks need manual reconciliation')
                    old_binding = json.loads(old['review_binding']) if old['review_binding'] else None
                    if old['review_of'] != review_of or old_binding != review_binding:
                        raise Rejected(409, 'A retry must preserve the original review source binding')
                    if self.db.execute('SELECT 1 FROM tasks WHERE supersedes=?',(supersedes,)).fetchone():
                        raise Rejected(409, 'Task was already retried')
                    attempts, cursor = 1, old
                    while cursor['supersedes']:
                        attempts, cursor = attempts + 1, self.db.execute('SELECT * FROM tasks WHERE id=?',(cursor['supersedes'],)).fetchone()
                    if attempts >= MAX_ATTEMPTS:
                        raise Rejected(409, 'Retry limit reached for this role')
                    if plan:
                        membership = self._fanout_membership(old)
                        if (not membership or membership[0]['id'] != plan['id']
                                or membership[1]['logical_role'] != role
                                or membership[1]['stage'] != stage
                                or access != 'read'):
                            raise Rejected(409, 'Automatic fanout plans accept planned-member retries only')
                elif self.db.execute('SELECT count(*) FROM tasks WHERE parent_id=? AND id NOT IN (SELECT supersedes FROM tasks WHERE supersedes IS NOT NULL)',(parent_id,)).fetchone()[0] >= MAX_CHILDREN:
                    raise Rejected(409, 'Parent already has the maximum number of children')
            tid, now = uuid.uuid4().hex, self.clock()
            self.db.execute('INSERT INTO tasks(id,owner,project,title,brief,runtime,category,idem,request_hash,status,created,updated,business_context) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (tid,owner,project,self.sanitize(body.get('title') or 'Fleet task'),self.sanitize(body['brief']),runtime,
               self.sanitize(COMMERCIAL_PREPARATION_CATEGORY if business_context is not None else body.get('category') or 'development'),
               body['idempotency_key'],digest,'queued',now,now,
               json.dumps(business_context, sort_keys=True, separators=(',', ':')) if business_context is not None else None))
            if worker_id is not None:
                self.db.execute('UPDATE tasks SET requested_worker=? WHERE id=?', (worker_id, tid))
            if parent_id is not None:
                self.db.execute('UPDATE tasks SET parent_id=?,logical_role=?,stage=?,supersedes=?,access=? WHERE id=?',(parent_id,role,stage,supersedes,access,tid))
            if review_of is not None:
                current_binding = self._review_binding_for_submission(owner, project, parent_id, review_of)
                if current_binding != review_binding:
                    raise Rejected(409, 'Write review source changed during submission')
                self.db.execute('UPDATE tasks SET review_of=?,review_binding=? WHERE id=?',
                                (review_of, json.dumps(review_binding, sort_keys=True, separators=(',', ':')), tid))
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
        self._need(principal, 'read')
        owners = [owner, *principal.get('view_owners', [])]
        with self.transaction():
            self._expire()
            return [self._public(r) for r in self.db.execute('SELECT * FROM tasks WHERE owner IN (%s) ORDER BY created DESC LIMIT 200' % ','.join('?' * len(owners)),owners) if r['project'] in principal['projects']]

    def detail(self, owner, principal, tid, events=False):
        self._need(principal, 'read')
        with self.transaction():
            self._expire()
            row = self._owned(owner,principal,tid)
            if events:
                return [dict(r) for r in self.db.execute('SELECT seq,attempt_id,event_id,type,message,created FROM events WHERE task_id=? ORDER BY seq LIMIT 1000',(tid,))]
            result = self._public(row)
            if row['parent_id'] is None:
                result['graph'] = self._graph(row)
                result['fanout_action'] = self._fanout_action(owner, principal, row)
            else:
                context = self._fanout_context(row)
                if context:
                    result['fanout'] = {'plan_id': context['plan_id'], 'order': context['order']}
                    if context.get('hold_reason'):
                        result['hold_reason'] = context['hold_reason']
                review_hold = self._review_hold(row)
                if review_hold:
                    result['hold_reason'] = review_hold
            return result

    def _graph(self, parent):
        kids = self.db.execute('SELECT * FROM tasks WHERE parent_id=? ORDER BY created',(parent['id'],)).fetchall()
        replaced = {kid['supersedes']: kid['id'] for kid in kids if kid['supersedes']}
        children = []
        for kid in kids:
            child = dict({k: v for k, v in self._public(kid).items()
                          if k in ('id','logical_role','stage','status','artifact','supersedes','review_of',
                                  'business_context','business_gate')},
                         superseded_by=replaced.get(kid['id']))
            context = self._fanout_context(kid)
            if context:
                child['fanout'] = {'plan_id': context['plan_id'], 'order': context['order']}
                if context.get('hold_reason'):
                    child['hold_reason'] = context['hold_reason']
            review_hold = self._review_hold(kid)
            if review_hold:
                child['hold_reason'] = review_hold
            children.append(child)
        kids = [kid for kid in kids if kid['id'] not in replaced]  # a retried attempt no longer counts
        statuses = {kid['status'] for kid in kids}
        if not kids:
            status = 'none'
        elif statuses & {'failed','interrupted'}:
            status = 'failed'
        elif 'cancelled' in statuses or 'cancel_requested' in statuses:
            status = 'cancelled'
        elif statuses == {'succeeded'} and parent['status'] == 'succeeded' and any(kid['logical_role'] == 'sentinel' and kid['artifact'] for kid in kids):
            status = 'verified'  # derived artifact rollup, not a semantic validation claim
        else:
            status = 'incomplete'
        result = {'children': children, 'status': status}
        context = self._context_from_row(parent)
        if context is not None:
            result['business_context'] = context
        return result

    def cancel(self, owner, principal, tid):
        self._need(principal, 'cancel')
        with self.transaction():
            self._expire()
            row = self._owned(owner,principal,tid,mutate=True)
            status = {'queued':'cancelled','running':'cancel_requested'}.get(row['status'],row['status'])
            now = self.clock()
            self.db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?',(status,now,tid))
            for kid in self.db.execute("SELECT id,status FROM tasks WHERE parent_id=? AND status IN ('queued','running')",(tid,)).fetchall():
                self.db.execute('UPDATE tasks SET status=?,updated=? WHERE id=?',({'queued':'cancelled','running':'cancel_requested'}[kid['status']],now,kid['id']))
            return self._public(self._owned(owner,principal,tid,mutate=True))

    def claim(self, name, worker):
        with self.transaction():
            self.db.execute('INSERT INTO worker_presence(worker,last_seen) VALUES(?,?) ON CONFLICT(worker) DO UPDATE SET last_seen=excluded.last_seen', (name, self.clock()))
            self._expire()
            active = self.db.execute("SELECT count(*) FROM tasks WHERE status IN ('running','cancel_requested')").fetchone()[0]
            if active >= min(1, int(self.config.get('capacity',1))):
                return None
            for row in self.db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created"):
                if row['requested_worker'] is not None and row['requested_worker'] != name:
                    continue
                if row['project'] not in worker['projects'] or row['runtime'] not in worker['runtimes']:
                    continue
                modes = worker.get('access_modes', ['read'] if worker.get('remote_artifacts') is True else ['read', 'write'])
                if row['access'] not in modes:
                    continue
                context = self._fanout_context(row)
                if context and context.get('hold_reason'):
                    continue
                review_evidence = None
                if row['review_of'] is not None or row['review_binding'] is not None:
                    review_evidence, review_hold = self._review_context(row)
                    if review_hold:
                        continue
                business_context = self._context_from_row(row)
                template = readiness = None
                if business_context is not None:
                    if context or review_evidence is not None:
                        # Business preparation never travels with fanout or
                        # write-review metadata; refuse an inconsistent row.
                        continue
                    try:
                        business_context, template, readiness = self._business_metadata(row['project'], business_context)
                    except Rejected:
                        # A changed server snapshot must never turn an already-queued
                        # price-dependent preparation into an execution permission.
                        continue
                attempt, token = uuid.uuid4().hex, uuid.uuid4().hex + uuid.uuid4().hex
                now = self.clock()
                self.db.execute("UPDATE tasks SET status='running',worker=?,attempt_id=?,lease_hash=?,deadline=?,updated=? WHERE id=?",(name,attempt,hashlib.sha256(token.encode()).hexdigest(),now+self.config.get('lease_seconds',90),now,row['id']))
                project = self.config['projects'][row['project']]
                result = self._public(self.db.execute('SELECT * FROM tasks WHERE id=?',(row['id'],)).fetchone())
                result.update(tenant=project['tenant'],organization=project['organization'],lease_token=token)
                if worker.get('remote_artifacts') is True:
                    # A remote worker receives a project identity, not a coordinator
                    # filesystem path. It resolves that identity through its own
                    # project_roots allowlist after an SSH loopback forward.
                    result['remote_artifacts'] = True
                else:
                    result.update(root=str(Path(project['root']).resolve()),artifacts_root=str(self.artifacts))
                if context:
                    result['fanout'] = {'plan_id': context['plan_id'], 'order': context['order']}
                    result['source_artifacts'] = context['source_artifacts']
                    if 'source_outputs' in context:
                        result['source_outputs'] = context['source_outputs']
                if review_evidence is not None:
                    result['review_evidence'] = review_evidence
                if business_context is not None:
                    result.update(
                        business_context=business_context,
                        business_template=template,
                        business_readiness=readiness,
                    )
                return result
            return None

    def _artifact_payload(self, artifact, max_bytes=16*1024*1024):
        if not isinstance(artifact,dict) or not isinstance(artifact.get('path'),str) or not isinstance(artifact.get('sha256'),str):
            raise Rejected(400,'Invalid artifact')
        path = Path(artifact['path'])
        if not path.is_absolute():
            path = self.artifacts / path
        resolved = path.resolve()
        if not resolved.is_relative_to(self.artifacts.resolve()) or path.is_symlink() or not resolved.is_file():
            raise Rejected(400,'Artifact outside allowed root or missing')
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise Rejected(400,'Artifact too large or not a regular file')
            payload = source.read(max_bytes + 1)
            after = os.fstat(source.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if len(payload) > max_bytes or identity(before) != identity(after):
            raise Rejected(400,'Artifact changed or too large')
        digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(digest,artifact['sha256']):
            raise Rejected(400,'Artifact hash mismatch')
        return {'path':str(resolved.relative_to(self.artifacts)), 'sha256':digest}, payload

    def _artifact(self, artifact):
        return self._artifact_payload(artifact)[0]

    def _redact_artifact_value(self, value, lease_token):
        """Redact every persisted remote-artifact string, including nested values."""
        if isinstance(value, str):
            return self.sanitize(value).replace(lease_token, '[REDACTED]') if lease_token else self.sanitize(value)
        if isinstance(value, list):
            return [self._redact_artifact_value(item, lease_token) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                safe_key = self.sanitize(key).replace(lease_token, '[REDACTED]') if lease_token else self.sanitize(key)
                if safe_key in result:
                    raise Rejected(400, 'Artifact redaction collision')
                result[safe_key] = self._redact_artifact_value(item, lease_token)
            return result
        return value

    def _write_remote_artifact(self, task, attempt, content):
        """Write a coordinator-generated artifact name without ever following worker paths."""
        filename = 'remote-%s-%s-%s.json' % (task, attempt, uuid.uuid4().hex)
        target = self.artifacts / filename
        temporary = self.artifacts / ('.%s.%s.tmp' % (filename, uuid.uuid4().hex))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(temporary, flags, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        return {'path': filename, 'sha256': hashlib.sha256(content).hexdigest()}

    def _remote_artifact(self, worker, row, artifact, lease_token):
        """Validate an inline remote artifact, redact it, then atomically persist it."""
        if (not isinstance(artifact, dict) or set(artifact) != {'content', 'sha256'} or
                not isinstance(artifact['content'], str) or
                not isinstance(artifact['sha256'], str) or
                not re.fullmatch(r'[a-f0-9]{64}', artifact['sha256'])):
            raise Rejected(400, 'Invalid remote artifact')
        content = artifact['content']
        # Check characters before encoding so a direct Coordinator caller cannot
        # force an unbounded allocation outside the HTTP boundary.
        if not 0 < len(content) <= MAX_REMOTE_ARTIFACT_BYTES:
            raise Rejected(413, 'Remote artifact is too large')
        try:
            raw = content.encode('utf-8')
        except UnicodeEncodeError:
            raise Rejected(400, 'Invalid remote artifact') from None
        if len(raw) > MAX_REMOTE_ARTIFACT_BYTES:
            raise Rejected(413, 'Remote artifact is too large')
        digest = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(digest, artifact['sha256']):
            raise Rejected(400, 'Remote artifact hash mismatch')
        envelope = _bounded_json_object(raw, MAX_REMOTE_ARTIFACT_BYTES,
                                        'Remote artifact is too large')
        node_id = worker.get('node_id')
        if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
            raise Rejected(403, 'Remote worker enrollment unavailable')
        expected = {
            'task_id': row['id'],
            'attempt_id': row['attempt_id'],
            'project': row['project'],
            'node': node_id,
            'runtime': row['runtime'],
        }
        if any(envelope.get(key) != value for key, value in expected.items()):
            raise Rejected(400, 'Remote artifact envelope mismatch')
        if not isinstance(envelope.get('output'), str):
            raise Rejected(400, 'Remote artifact output unavailable')
        try:
            stored = _canonical_json(self._redact_artifact_value(envelope, lease_token))
        except (TypeError, ValueError, UnicodeEncodeError):
            raise Rejected(400, 'Invalid remote artifact') from None
        if len(stored) > MAX_REMOTE_ARTIFACT_BYTES:
            raise Rejected(413, 'Remote artifact is too large')
        return self._write_remote_artifact(row['id'], row['attempt_id'], stored)

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
            self.db.execute('INSERT INTO worker_presence(worker,last_seen) VALUES(?,?) ON CONFLICT(worker) DO UPDATE SET last_seen=excluded.last_seen', (name, self.clock()))
            duplicate = self.db.execute('SELECT 1 FROM events WHERE task_id=? AND attempt_id=? AND event_id=?',(row['id'],row['attempt_id'],body['event_id'])).fetchone()
            if duplicate:
                return {'accepted':True,'duplicate':True,'cancel_requested':row['status']=='cancel_requested'}
            if row['status'] not in ('running','cancel_requested'):
                raise Rejected(409,'Assignment is no longer active')
            if kind == 'succeeded' and row['status'] == 'cancel_requested':
                raise Rejected(409,'Cancellation must be reconciled')
            if kind == 'succeeded':
                artifact = (self._remote_artifact(worker, row, body.get('artifact'), body['lease_token'])
                            if worker.get('remote_artifacts') is True
                            else self._artifact(body.get('artifact')))
            else:
                artifact = None
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
    remote_projects, local_projects = set(), set()
    for entry in config['workers'].values():
        remote = entry.get('remote_artifacts', False)
        if not isinstance(remote, bool):
            raise ValueError('Invalid remote artifact enrollment')
        projects = entry.get('projects')
        if isinstance(projects, list) and all(isinstance(project, str) for project in projects):
            (remote_projects if remote else local_projects).update(projects)
    for project_id, project in config['projects'].items():
        if not all(isinstance(project.get(key),str) and project[key] for key in ('tenant','organization')) or not isinstance(project.get('runtimes'),list):
            raise ValueError('Invalid project configuration')
        # A project served only by explicitly enrolled remote workers has no
        # coordinator filesystem dependency. Legacy/local workers retain the
        # existing checked-out Git root requirement.
        if project_id not in remote_projects or project_id in local_projects:
            root=Path(project.get('root',''))
            if not root.is_absolute() or not root.is_dir() or not (root/'.git').exists():
                raise ValueError('Project roots must name existing Git repositories')
        if 'fanout' in project and not isinstance(project['fanout'], bool):
            raise ValueError('Invalid project fanout configuration')
        if 'artifact_context' in project and not isinstance(project['artifact_context'], bool):
            raise ValueError('Invalid project artifact context configuration')
        if 'write_review_context' in project and not isinstance(project['write_review_context'], bool):
            raise ValueError('Invalid project write review context configuration')
    tokens=set()
    for group in ('principals','workers'):
        for entry in config[group].values():
            token=entry.get('token')
            if not isinstance(token,str) or len(token)<16 or token in tokens:
                raise ValueError('Credentials must be unique nonempty strings of at least 16 characters')
            tokens.add(token)
            if not isinstance(entry.get('projects'),list) or any(project not in config['projects'] for project in entry['projects']):
                raise ValueError('Invalid credential project scope')
            if group=='workers':
                if not isinstance(entry.get('runtimes'),list):
                    raise ValueError('Invalid worker runtime scope')
                modes = entry.get('access_modes', ['read'] if entry.get('remote_artifacts') is True else ['read', 'write'])
                if not isinstance(modes, list) or not modes or any(mode not in ('read', 'write') for mode in modes):
                    raise ValueError('Invalid worker access modes')
                if entry.get('remote_artifacts') is True:
                    node_id=entry.get('node_id')
                    if not isinstance(node_id,str) or not NODE_ID.fullmatch(node_id):
                        raise ValueError('Remote workers require a valid node_id')
            if group == 'principals' and 'fanout_projects' in entry:
                if (not isinstance(entry['fanout_projects'], list)
                        or any(project not in config['projects'] for project in entry['fanout_projects'])):
                    raise ValueError('Invalid fanout project scope')
            if group=='principals':
                permissions,viewed=entry.get('permissions',list(PERMISSIONS)),entry.get('view_owners',[])
                if not isinstance(permissions,list) or not set(permissions)<=set(VALID_PERMISSIONS):
                    raise ValueError('Invalid principal permissions')
                if not isinstance(viewed,list) or not all(isinstance(name,str) and name in config['principals'] for name in viewed):
                    raise ValueError('Invalid principal view_owners')
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
                    length_header = self.headers.get('Content-Length','')
                    if not re.fullmatch(r'[0-9]{1,8}', length_header):
                        raise Rejected(413,'Invalid body size')
                    length = int(length_header)
                    # Only the fanout action may carry an empty body; every
                    # other POST keeps the bounded, non-empty JSON contract.
                    empty_fanout = bool(re.fullmatch(r'/v1/tasks/[a-f0-9]{32}/fanout', path))
                    if not 0 <= length <= MAX_HTTP_BODY_BYTES or (length == 0 and not empty_fanout):
                        raise Rejected(413,'Invalid body size')
                    if length == 0:
                        body = {}
                    else:
                        raw = self.rfile.read(length)
                        if len(raw) != length:
                            raise Rejected(400,'Incomplete request body')
                        body = _bounded_json_object(raw, MAX_HTTP_BODY_BYTES)
                if not worker_route and path == '/v1/context' and self.command == 'GET':
                    result = coordinator.capabilities.context(principal)
                elif not worker_route and path == '/v1/capabilities' and self.command == 'GET':
                    result = coordinator.capabilities.list(principal)
                elif not worker_route and path == '/v1/capabilities/execute' and self.command == 'POST':
                    result = coordinator.capabilities.execute(name, principal, body)
                elif not worker_route and path == '/v1/approvals' and self.command == 'GET':
                    result = coordinator.capabilities.approvals(name, principal)
                elif not worker_route and path == '/v1/approvals' and self.command == 'POST':
                    result = coordinator.capabilities.request_approval(name, principal, body)
                elif not worker_route and re.fullmatch(r'/v1/approvals/[a-f0-9]{32}/(?:approve|reject)', path) and self.command == 'POST':
                    parts = path.split('/')
                    result = coordinator.capabilities.decide(name, principal, parts[3], 'approved' if parts[4] == 'approve' else 'rejected', body)
                elif not worker_route and re.fullmatch(r'/v1/tasks/[a-f0-9]{32}/artifact', path) and self.command == 'GET':
                    result = coordinator.capabilities.artifact(name, principal, path.split('/')[3])
                elif path=='/v1/worker/claim' and self.command=='POST':
                    result={'task':coordinator.claim(name,principal)}
                elif path=='/v1/worker/report' and self.command=='POST':
                    result=coordinator.report(name,principal,body)
                elif path=='/v1/tasks' and self.command=='GET':
                    result={'tasks':coordinator.list_tasks(name,principal)}
                elif path=='/v1/tasks' and self.command=='POST':
                    result=coordinator.submit(name,principal,body)
                elif not worker_route and re.fullmatch(r'/v1/tasks/[a-f0-9]{32}(?:/(?:events|cancel|fanout))?',path):
                    parts=path.split('/')
                    if self.command=='POST' and len(parts)==5 and parts[4]=='cancel':
                        result=coordinator.cancel(name,principal,parts[3])
                    elif self.command=='POST' and len(parts)==5 and parts[4]=='fanout':
                        result=coordinator.fanout(name,principal,parts[3],body)
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
