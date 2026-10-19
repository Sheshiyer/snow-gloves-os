"""Founder asks served and answered through the fleet coordinator.

The pure deriver in `tenant_asks` turns tenant files into asks with stable ids.
This module lists them per project and records founder answers in SQLite plus
an append-only journal under the tenant's `asks/` directory. SQLite is the
authority: each answer commits together with an outbox row, and the journal is
appended only after that commit; unwritten outbox rows are retried on the next
answer, listing and coordinator start. Listing needs the
`read` permission; answering needs `approve`. Writes are fail-closed: answers
are re-derived at answer time, bounded to 500 characters, filtered for
sensitive values, and the journal never follows a symlink or resolves outside
the private tenants directory.
"""
import json
import os
import re
import threading
import uuid
from pathlib import Path

from . import paths
from .fleet_capabilities import reject
from .tenant_asks import CONTROL_RE, SENSITIVE_RE, derive_asks, is_scalar_text, load_catalog, load_proposal

MAX_ANSWER = 500
MAX_PRINCIPAL = 120  # the client's answered_by limit
ASK_ID = re.compile(r'[a-f0-9]{32}\Z')


def install(coordinator):
    coordinator.db.executescript('''
      CREATE TABLE IF NOT EXISTS ask_answers (
        project TEXT NOT NULL, ask_id TEXT NOT NULL, tenant TEXT NOT NULL, kind TEXT NOT NULL,
        answer_json TEXT NOT NULL, answered REAL NOT NULL, answered_by TEXT NOT NULL,
        proposed TEXT, PRIMARY KEY(project, ask_id));
      CREATE TABLE IF NOT EXISTS ask_journal_outbox (
        answer_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, record_json TEXT NOT NULL, created REAL NOT NULL);
    ''')
    columns = {row[1] for row in coordinator.db.execute('PRAGMA table_info(ask_answers)')}
    if 'proposed' not in columns:
        coordinator.db.execute('ALTER TABLE ask_answers ADD COLUMN proposed TEXT')


def _display_principal(owner):
    """The principal name as shown to clients: no control characters, at most 120 code points."""
    text = owner if isinstance(owner, str) else ''
    text = ''.join('\ufffd' if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in text)  # lone surrogates
    text = ' '.join(CONTROL_RE.sub(' ', text).split())
    return text[:MAX_PRINCIPAL] or 'principal'


class Asks:
    def __init__(self, coordinator):
        self.c = coordinator
        # One flush at a time: select, append and delete never interleave across
        # request threads, so each record is appended once and in commit order.
        self._flush_lock = threading.Lock()

    @staticmethod
    def _reconcile(ask, answer, proposed=None):
        """Keep an answered ask in the shape, and with the proposal, it was answered with.

        A proposal imported after a typed answer would otherwise turn the ask
        into yes/no while the stored answer still holds a value; a yes/no answer
        keeps the proposed value it accepted or rejected even if that proposal
        is no longer derived.
        """
        if not isinstance(answer, dict):
            return ask
        if 'value' in answer and ask['answer_type'] != 'text':
            return dict(ask, answer_type='text', proposed=None)
        if 'accept' in answer:
            snapshot = proposed if isinstance(proposed, str) and proposed else ask['proposed']
            if ask['answer_type'] != 'yes_no' or snapshot != ask['proposed']:
                return dict(ask, answer_type='yes_no', proposed=snapshot)
        return ask

    @staticmethod
    def _public_ask(ask, project, answer, answered, answered_by):
        result = dict(ask)
        result.update(project=project, status='answered' if answer is not None else 'open',
                      answer=answer, answered=answered, answered_by=answered_by)
        return result

    @staticmethod
    def _validated_answer(ask, body):
        if not isinstance(body, dict):
            reject(400, 'Invalid answer')
        if ask['answer_type'] == 'text':
            if set(body) != {'value'}:
                reject(400, 'Invalid answer')
            value = body['value']
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_ANSWER:
                reject(400, 'Invalid answer')
            if SENSITIVE_RE.search(value) or CONTROL_RE.search(value) or not is_scalar_text(value):
                reject(400, 'Invalid answer')
            return {'value': value}
        if set(body) != {'accept'}:
            reject(400, 'Invalid answer')
        accept = body['accept']
        if not isinstance(accept, bool):
            reject(400, 'Invalid answer')
        return {'accept': accept}

    def _derive_ask(self, tenant, ask_id):
        asks = derive_asks(paths.tenants_dir(), tenant, load_proposal(paths.data_root()), load_catalog(paths.code_root()))
        for ask in asks:
            if ask['id'] == ask_id:
                return ask
        reject(404, 'Ask not found')

    def _journal_path(self, tenant):
        tenants_dir = paths.tenants_dir().resolve()
        tenant_dir = tenants_dir / tenant
        if tenant_dir.is_symlink() or not tenant_dir.is_dir():
            reject(503, 'Ask journal unavailable')
        asks_dir = tenant_dir / 'asks'
        if asks_dir.is_symlink():
            reject(503, 'Ask journal unavailable')
        if not asks_dir.exists():
            try:
                asks_dir.mkdir(mode=0o700)
            except OSError:
                reject(503, 'Ask journal unavailable')
        if not asks_dir.resolve().is_relative_to(tenants_dir):
            reject(503, 'Ask journal unavailable')
        return asks_dir / 'answers.jsonl'

    @staticmethod
    def _last_newline(fd, end):
        """Offset just past the last newline before *end*, or 0 when there is none."""
        offset = end
        while offset > 0:
            start = max(0, offset - 65536)
            index = os.pread(fd, offset - start, start).rfind(b'\n')
            if index != -1:
                return start + index + 1
            offset = start
        return 0

    @staticmethod
    def _open_journal(path):
        """Open tenants/<tenant>/asks/answers.jsonl one component at a time.

        Each directory is opened with O_NOFOLLOW and the next name is resolved
        relative to the held descriptor, so swapping the tenant or asks
        directory for a link after validation cannot redirect the append.
        """
        nofollow = getattr(os, 'O_NOFOLLOW', 0)
        directory = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | nofollow
        handles = [os.open(path.parents[2], os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))]
        try:
            for name in (path.parents[1].name, path.parent.name):
                handles.append(os.open(name, directory, dir_fd=handles[-1]))
            return os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_APPEND | nofollow, 0o600, dir_fd=handles[-1])
        finally:
            for handle in handles:
                os.close(handle)

    @classmethod
    def _append_journal(cls, path, record):
        """Append one JSON line, first truncating any incomplete tail a failed write left.

        Appends are serialized by the flush lock and this journal has no other
        writer, so bytes after the last newline can only be our own partial line.
        A crash after the fsync but before the outbox row is deleted leaves this
        record as the last line, so a retry that finds it there appends nothing.
        """
        try:
            line = (json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')
        except UnicodeEncodeError:
            # Never let one unencodable record block the outbox: ASCII escapes are valid JSON.
            line = (json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        try:
            fd = cls._open_journal(Path(path))
        except OSError:
            reject(503, 'Ask journal unavailable')
        try:
            size = os.fstat(fd).st_size
            if size:
                keep = cls._last_newline(fd, size)
                if keep != size:
                    os.ftruncate(fd, keep)
                if keep:
                    start = cls._last_newline(fd, keep - 1)
                    if keep - start <= 1024 * 1024:
                        try:
                            last = json.loads(os.pread(fd, keep - start, start))
                        except ValueError:
                            last = None
                        if isinstance(last, dict) and last.get('answer_id') == record.get('answer_id'):
                            return
            view = memoryview(line)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        except OSError:
            reject(503, 'Ask journal unavailable')
        finally:
            os.close(fd)

    def list(self, owner, principal, project):
        self.c._need(principal, 'read')
        cfg = self.c.capabilities.project(principal, project)
        self.flush(cfg['tenant'])
        with self.c.lock:
            rows = {row['ask_id']: row for row in self.c.db.execute(
                'SELECT * FROM ask_answers WHERE project=?', (project,))}
        asks = derive_asks(paths.tenants_dir(), cfg['tenant'], load_proposal(paths.data_root()), load_catalog(paths.code_root()))
        public = []
        for ask in asks:
            row = rows.get(ask['id'])
            if row is None:
                public.append(self._public_ask(ask, project, None, None, None))
            else:
                answer = json.loads(row['answer_json'])
                public.append(self._public_ask(self._reconcile(ask, answer, row['proposed']), project, answer,
                                               row['answered'], row['answered_by']))
        return {'asks': public}

    def answer(self, owner, principal, project, ask_id, body):
        self.c._need(principal, 'approve')
        cfg = self.c.capabilities.project(principal, project)
        if not isinstance(ask_id, str) or not ASK_ID.fullmatch(ask_id):
            reject(400, 'Invalid ask id')
        tenant = cfg['tenant']
        with self.c.transaction():
            ask = self._derive_ask(tenant, ask_id)
            prior = self.c.db.execute('SELECT answer_json, proposed FROM ask_answers WHERE project=? AND ask_id=?',
                                      (project, ask_id)).fetchone()
            if prior is not None:
                ask = self._reconcile(ask, json.loads(prior['answer_json']), prior['proposed'])
            answer = self._validated_answer(ask, body)
            self._journal_path(tenant)  # refuse up front if the journal can never be written
            now = self.c.clock()
            by = _display_principal(owner)
            # A yes/no answer is only meaningful with the value it accepted or rejected.
            proposed = ask['proposed'] if 'accept' in answer else None
            record = {'answer_id': uuid.uuid4().hex, 'ask_id': ask_id, 'project': project, 'tenant': tenant,
                      'kind': ask['kind'], 'title': ask['title'], 'answer': answer, 'proposed': proposed,
                      'answered': now, 'answered_by': by}
            self.c.db.execute('''
              INSERT INTO ask_answers(project, ask_id, tenant, kind, answer_json, answered, answered_by, proposed)
              VALUES(?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(project, ask_id) DO UPDATE SET
                tenant=excluded.tenant, kind=excluded.kind, answer_json=excluded.answer_json,
                answered=excluded.answered, answered_by=excluded.answered_by, proposed=excluded.proposed
            ''', (project, ask_id, tenant, ask['kind'],
                  json.dumps(answer, sort_keys=True, separators=(',', ':')), now, by, proposed))
            self.c.db.execute('INSERT INTO ask_journal_outbox(answer_id, tenant, record_json, created) VALUES(?, ?, ?, ?)',
                              (record['answer_id'], tenant, json.dumps(record, sort_keys=True), now))
        # The answer is durable in SQLite; the journal follows, never precedes, it.
        self.flush(tenant)
        return {'ask': self._public_ask(self._reconcile(ask, answer, proposed), project, answer, now, by)}

    def flush(self, tenant=None):
        """Append committed outbox records to their journals; a failed append stays queued."""
        from .fleet_coordinator import Rejected
        with self._flush_lock:
            with self.c.lock:
                query, params = 'SELECT rowid, * FROM ask_journal_outbox', ()
                if tenant is not None:
                    query, params = query + ' WHERE tenant=?', (tenant,)
                rows = list(self.c.db.execute(query + ' ORDER BY rowid', params))
            blocked = set()
            for row in rows:
                # Keep per-tenant order: once one record fails, later ones wait.
                if row['tenant'] in blocked:
                    continue
                try:
                    self._append_journal(self._journal_path(row['tenant']), json.loads(row['record_json']))
                except (Rejected, OSError, ValueError):
                    blocked.add(row['tenant'])
                    continue
                with self.c.transaction():
                    self.c.db.execute('DELETE FROM ask_journal_outbox WHERE answer_id=?', (row['answer_id'],))
