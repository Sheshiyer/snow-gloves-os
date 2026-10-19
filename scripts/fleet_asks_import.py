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


def _scan_journal(path):
    """Full streaming scan: latest (proposal, task time) per ask id and every fully imported source.

    A source counts as imported only once its completion line is on disk, so an
    import cut short is retried. Lines written before completion lines existed
    (no ``created`` key) came from one fsynced write and count as complete.
    """
    latest, done = {}, set()
    try:
        if path.is_symlink() or not path.is_file():
            return latest, done
        with path.open('r', encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if isinstance(record.get('ask_id'), str) and isinstance(record.get('proposed'), str):
                    latest[record['ask_id']] = (record['proposed'], _task_time(record.get('created')))
                if isinstance(record.get('source'), str) and (record.get('complete') is True or 'created' not in record):
                    done.add(record['source'])
    except OSError:
        pass
    return latest, done


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
    base = Path(tenants_dir).resolve()
    asks_dir = Path(tenants_dir) / tenant / 'asks'
    if asks_dir.is_symlink() or not asks_dir.resolve().is_relative_to(base):
        return 0
    asks_dir.mkdir(parents=True, exist_ok=True)
    path = asks_dir / 'proposed.jsonl'
    flags = os.O_APPEND | os.O_CREAT | os.O_RDWR
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'a+b') as stream:
        # Concurrent imports for one tenant scan and append under one lock, so
        # task order and completion checks see every earlier write.
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        # Dedupe against the whole journal, not the bounded display tail, and never
        # re-import a finished task: an old artifact must not override a newer proposal.
        recorded, imported = _scan_journal(path)
        if source is not None and source in imported:
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
