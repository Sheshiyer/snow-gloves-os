#!/usr/bin/env python3
"""Import agent research proposals into a tenant's ask proposal journal."""
import argparse
import fcntl
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from lib.tenant_asks import CONTROL_RE as CONTROL_CHARS, SENSITIVE_RE, is_scalar_text, load_proposals

_ARRAY_OF_OBJECTS = re.compile(r'\[\s*\{')
MAX_PROPOSED = 500
MAX_EVIDENCE = 500
MAX_ARTIFACT = 256 * 1024
MAX_JOURNAL_LINE = 64 * 1024  # one journal record; the importer writes far less
JOURNAL = 'proposed.jsonl'
COMPACT_AT = 4 * 1024 * 1024  # past this, the journal is rewritten to its live records
_MAX_FAILED_DECODES = 2000


def _last_json_array(text):
    """Return the last top-level JSON array of proposal objects in *text*, or None.

    One forward pass over candidate openers ('[' then '{'). A successfully
    decoded array is skipped as a whole, so arrays and strings nested inside a
    proposal are never candidates. The text is capped at MAX_ARTIFACT, and
    at most _MAX_FAILED_DECODES failed decode attempts are made.
    """
    decoder = json.JSONDecoder()
    found, pos, failures = None, 0, 0
    while failures < _MAX_FAILED_DECODES:
        match = _ARRAY_OF_OBJECTS.search(text, pos)
        if match is None:
            break
        try:
            value, end = decoder.raw_decode(text, match.start())
        except (ValueError, json.JSONDecodeError):
            failures += 1
            pos = match.start() + 1
            continue
        if isinstance(value, list) and value and all(isinstance(item, dict) and 'ask_id' in item for item in value):
            found = value
        pos = end
    return found


def _task_time(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def _scan_journal(stream, ask_ids, source):
    """Bounded streaming scan of the held journal: the latest (proposal, task time) for
    each of *ask_ids*, and whether *source* has fully imported.

    Only those ids are kept and lines longer than MAX_JOURNAL_LINE are skipped
    whole, so an old or damaged journal never grows memory. A source counts as
    imported only once its completion line is on disk, so an import cut short is
    retried. Lines written before completion lines existed (no ``created`` key)
    came from one fsynced write and count as complete.
    """
    latest, done = {}, False
    stream.seek(0)
    while True:
        line = stream.readline(MAX_JOURNAL_LINE + 1)
        if not line:
            break
        if len(line) > MAX_JOURNAL_LINE:
            while line and not line.endswith(b'\n'):
                line = stream.readline(MAX_JOURNAL_LINE)
            continue
        try:
            record = json.loads(line.decode('utf-8', errors='replace'))
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get('ask_id') in ask_ids and isinstance(record.get('proposed'), str):
            latest[record['ask_id']] = (record['proposed'], _task_time(record.get('created')))
        if source is not None and record.get('source') == source and (record.get('complete') is True or 'created' not in record):
            done = True
    return latest, done


def _open_journal(tenants_dir, tenant):
    """Hold tenants/<tenant>/asks/, opening one component at a time.

    Only the data root (tenants/'s parent) is opened by path. tenants/ is then
    opened with O_NOFOLLOW, and the tenant and asks directories are created if
    missing and opened the same way relative to the held parent, so a link at
    any of them (placed before or after any check) can never redirect the append.
    """
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    directory = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
    tenants_dir = Path(tenants_dir).absolute()
    tenants_dir.parent.mkdir(parents=True, exist_ok=True)
    handles = [os.open(tenants_dir.parent, directory)]
    try:
        for name in (tenants_dir.name, tenant, 'asks'):
            try:
                os.mkdir(name, 0o700, dir_fd=handles[-1])
            except FileExistsError:
                pass
            handles.append(os.open(name, directory | nofollow, dir_fd=handles[-1]))
        asks = os.dup(handles[-1])
    finally:
        for handle in handles:
            os.close(handle)
    return asks


def _locked_journal(asks):
    """The journal opened in the held asks directory and locked, retrying if compaction
    replaced the file between our open and our lock."""
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    while True:
        fd = os.open(JOURNAL, os.O_APPEND | os.O_CREAT | os.O_RDWR | nofollow, 0o600, dir_fd=asks)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            if os.fstat(fd).st_ino == os.stat(JOURNAL, dir_fd=asks, follow_symlinks=False).st_ino:
                return fd
        except FileNotFoundError:
            pass
        os.close(fd)


def _compact(stream, asks):
    """Rewrite a large journal to the latest proposal per ask plus one completion line per
    imported source, so every later scan (each ask listing reads it) stays small.

    Runs under the journal lock; the new file replaces the old atomically, and waiting
    importers notice the replacement and reopen.
    """
    latest, done = {}, {}
    stream.seek(0)
    for line in stream:
        try:
            record = json.loads(line.decode('utf-8', errors='replace'))
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if isinstance(record.get('ask_id'), str) and isinstance(record.get('proposed'), str):
            latest.pop(record['ask_id'], None)
            latest[record['ask_id']] = record
        if isinstance(record.get('source'), str) and (record.get('complete') is True or 'created' not in record):
            done[record['source']] = _task_time(record.get('created'))
    body = b''.join(json.dumps(record).encode() + b'\n' for record in latest.values())
    body += b''.join(json.dumps({'source': source, 'created': when, 'complete': True}).encode() + b'\n'
                     for source, when in done.items())
    temp = JOURNAL + '.compact'
    try:
        os.unlink(temp, dir_fd=asks)
    except FileNotFoundError:
        pass
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=asks)
    try:
        view = memoryview(body)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, JOURNAL, src_dir_fd=asks, dst_dir_fd=asks)
    os.fsync(asks)


def import_proposals(tenants_dir, tenant, artifact_text, known_ids, source=None, created=None):
    """Append valid proposals from *artifact_text* to ``asks/proposed.jsonl``.

    Only entries whose ``ask_id`` is in *known_ids* and whose ``proposed``
    value is <= 500 characters and passes the sensitive filter are kept.
    ``evidence`` is capped at 500 characters and must also pass the sensitive
    filter; an entry is dropped if either value matches.  *created* is the
    source task's creation time: a proposal from a task older than the one
    that set the current proposal is dropped.  Returns the number of
    proposal lines written.
    """
    if len(artifact_text) > MAX_ARTIFACT:
        return 0
    array = _last_json_array(artifact_text)
    if not array:
        return 0
    created = _task_time(created)
    valid = []
    for entry in array:
        if not isinstance(entry, dict):
            continue
        ask_id = entry.get('ask_id')
        proposed = entry.get('proposed')
        if not isinstance(ask_id, str) or ask_id not in known_ids:
            continue
        if (not isinstance(proposed, str) or not proposed.strip() or len(proposed) > MAX_PROPOSED
                or CONTROL_CHARS.search(proposed) or not is_scalar_text(proposed)):
            continue
        if SENSITIVE_RE.search(proposed):
            continue
        record = {'ask_id': ask_id, 'proposed': proposed}
        evidence = entry.get('evidence')
        if isinstance(evidence, str):
            evidence = evidence[:MAX_EVIDENCE]
            if SENSITIVE_RE.search(evidence) or not is_scalar_text(evidence):
                continue
            record['evidence'] = evidence
        valid.append(record)
    if not valid and source is None:
        return 0
    # Same rule derive_asks() applies: the tenant directory is a real directory
    # directly under tenants/, never a link to another tenant, and so is asks/.
    if not isinstance(tenant, str) or not tenant or tenant in ('.', '..') or '/' in tenant or '\\' in tenant or '\0' in tenant:
        return 0
    try:
        asks = _open_journal(tenants_dir, tenant)
    except OSError:
        return 0
    try:
        # Concurrent imports for one tenant scan and append under one lock, so
        # task order and completion checks see every earlier write.
        fd = _locked_journal(asks)
    except OSError:
        os.close(asks)
        return 0
    try:
        with os.fdopen(fd, 'a+b') as stream:
            # Dedupe against the whole journal, not the bounded display tail, and never
            # re-import a finished task: an old artifact must not override a newer proposal.
            recorded, imported = _scan_journal(stream, {record['ask_id'] for record in valid}, source)
            if imported:
                return 0
            latest = {}
            for record in valid:
                latest[record['ask_id']] = record

            def fresh(record):
                current, current_time = recorded.get(record['ask_id'], (None, None))
                if current == record['proposed']:
                    return False
                # A task imported late must not replace a proposal from a newer task.
                return created is None or current_time is None or created >= current_time
            rows = [r for r in latest.values() if fresh(r)]
            if source is not None:
                rows = [dict(r, source=source, created=created) for r in rows]
            elif not rows:
                return 0
            size = os.fstat(stream.fileno()).st_size
            # A torn last line would swallow the first new record; end it first.
            lines = [b''] if size and os.pread(stream.fileno(), 1, size - 1) != b'\n' else []
            lines += [json.dumps(record).encode() for record in rows]
            # Every task ends with a completion line written after its proposals, so an
            # interrupted import is retried; load_proposals ignores lines without ask_id.
            if source is not None:
                lines.append(json.dumps({'source': source, 'created': created, 'complete': True}).encode())
            stream.write(b'\n'.join(lines) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
            if os.fstat(stream.fileno()).st_size > COMPACT_AT:
                try:
                    _compact(stream, asks)
                except OSError:
                    pass  # the appended journal is intact; compaction retries on the next import
    finally:
        os.close(asks)
    return len(rows)


def _get(coordinator, token, path):
    request = urllib.request.Request(
        coordinator.rstrip('/') + path,
        headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        print('HTTP %d' % exc.code, file=sys.stderr)
        raise SystemExit(1)
    except (urllib.error.URLError, OSError, ValueError):
        print('Fleet coordinator unavailable', file=sys.stderr)
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coordinator', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--task', required=True)
    args = parser.parse_args()
    token = Path(args.token_file).read_text().strip()
    task = _get(args.coordinator, token, '/v1/tasks/' + args.task)
    project = task.get('project')
    tenant = task.get('tenant')
    if not project or not tenant:
        print('Task project or tenant unavailable', file=sys.stderr)
        return 1
    artifact = _get(args.coordinator, token, '/v1/tasks/%s/artifact' % args.task)
    content = artifact.get('artifact', {}).get('content', {})
    output = content.get('output', '') if isinstance(content, dict) else ''
    if not output:
        print('Artifact output unavailable', file=sys.stderr)
        return 1
    try:
        from lib import paths
    except ImportError:
        print('paths module unavailable', file=sys.stderr)
        return 1
    tenants_dir = paths.tenants_dir()
    listing = _get(args.coordinator, token, '/v1/asks/' + project)
    # Only open asks take proposals; an answered ask keeps the founder's answer.
    known_ids = {ask['id'] for ask in (listing.get('asks') if isinstance(listing, dict) else [])
                 if isinstance(ask, dict) and isinstance(ask.get('id'), str) and ask.get('status') == 'open'}
    count = import_proposals(tenants_dir, tenant, output, known_ids, source="task:" + args.task,
                             created=task.get('created'))
    print('Imported %d proposal(s)' % count)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
