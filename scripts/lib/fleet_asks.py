"""Founder asks served and answered through the fleet coordinator.

The pure deriver in `tenant_asks` turns tenant files into asks with stable ids.
This module lists them per project and records founder answers in SQLite plus
an append-only journal under the tenant's `asks/` directory. Listing needs the
`read` permission; answering needs `approve`. Writes are fail-closed: answers
are re-derived at answer time, bounded to 500 characters, filtered for
sensitive values, and the journal never follows a symlink or resolves outside
the private tenants directory.
"""
import json
import os
import re

from . import paths
from .fleet_capabilities import reject
from .tenant_asks import CONTROL_RE, SENSITIVE_RE, derive_asks, load_proposal

MAX_ANSWER = 500
ASK_ID = re.compile(r'[a-f0-9]{32}\Z')


def install(coordinator):
    coordinator.db.executescript('''
      CREATE TABLE IF NOT EXISTS ask_answers (
        project TEXT NOT NULL, ask_id TEXT NOT NULL, tenant TEXT NOT NULL, kind TEXT NOT NULL,
        answer_json TEXT NOT NULL, answered REAL NOT NULL, answered_by TEXT NOT NULL,
        PRIMARY KEY(project, ask_id));
    ''')


class Asks:
    def __init__(self, coordinator):
        self.c = coordinator

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
            if not isinstance(value, str) or not 0 < len(value) <= MAX_ANSWER:
                reject(400, 'Invalid answer')
            if SENSITIVE_RE.search(value) or CONTROL_RE.search(value):
                reject(400, 'Invalid answer')
            return {'value': value}
        if set(body) != {'accept'}:
            reject(400, 'Invalid answer')
        accept = body['accept']
        if not isinstance(accept, bool):
            reject(400, 'Invalid answer')
        return {'accept': accept}

    def _derive_ask(self, tenant, ask_id):
        asks = derive_asks(paths.tenants_dir(), tenant, load_proposal(paths.data_root()))
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
    def _append_journal(path, record):
        line = json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n'
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, 'O_NOFOLLOW'):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o600)
        except OSError:
            reject(503, 'Ask journal unavailable')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(line.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            reject(503, 'Ask journal unavailable')

    def list(self, owner, principal, project):
        self.c._need(principal, 'read')
        cfg = self.c.capabilities.project(principal, project)
        with self.c.lock:
            rows = {row['ask_id']: row for row in self.c.db.execute(
                'SELECT * FROM ask_answers WHERE project=?', (project,))}
        asks = derive_asks(paths.tenants_dir(), cfg['tenant'], load_proposal(paths.data_root()))
        public = []
        for ask in asks:
            row = rows.get(ask['id'])
            if row is None:
                public.append(self._public_ask(ask, project, None, None, None))
            else:
                public.append(self._public_ask(ask, project, json.loads(row['answer_json']),
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
            answer = self._validated_answer(ask, body)
            journal_path = self._journal_path(tenant)
            now = self.c.clock()
            record = {'ask_id': ask_id, 'project': project, 'tenant': tenant, 'kind': ask['kind'],
                      'title': ask['title'], 'answer': answer, 'answered': now, 'answered_by': owner}
            self.c.db.execute('''
              INSERT INTO ask_answers(project, ask_id, tenant, kind, answer_json, answered, answered_by)
              VALUES(?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(project, ask_id) DO UPDATE SET
                tenant=excluded.tenant, kind=excluded.kind, answer_json=excluded.answer_json,
                answered=excluded.answered, answered_by=excluded.answered_by
            ''', (project, ask_id, tenant, ask['kind'],
                  json.dumps(answer, sort_keys=True, separators=(',', ':')), now, owner))
            self._append_journal(journal_path, record)
        return {'ask': self._public_ask(ask, project, answer, now, owner)}
