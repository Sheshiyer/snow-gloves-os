#!/usr/bin/env python3
"""Import agent research proposals into a tenant's ask proposal journal."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from lib.tenant_asks import SENSITIVE_RE

MAX_PROPOSED = 500
MAX_EVIDENCE = 500
MAX_ARTIFACT = 256 * 1024
_MAX_SCAN_ATTEMPTS = 200


def _last_json_array(text):
    """Return the last valid JSON array found in *text*, or None.

    Candidate '[' positions are walked from the end of *text* via rfind and
    ``raw_decode`` is tried at each, stopping at the first that decodes to a
    list.  At most 200 positions are examined, so the search is bounded even
    when the text contains thousands of '[' characters.
    """
    decoder = json.JSONDecoder()
    pos = len(text)
    for _ in range(_MAX_SCAN_ATTEMPTS):
        idx = text.rfind('[', 0, pos)
        if idx == -1:
            break
        try:
            value, _end = decoder.raw_decode(text, idx)
        except (ValueError, json.JSONDecodeError):
            pos = idx
            continue
        if isinstance(value, list):
            return value
        pos = idx
    return None


def import_proposals(tenants_dir, tenant, artifact_text, known_ids):
    """Append valid proposals from *artifact_text* to ``asks/proposed.jsonl``.

    Only entries whose ``ask_id`` is in *known_ids* and whose ``proposed``
    value is <= 500 characters and passes the sensitive filter are kept.
    ``evidence`` is capped at 500 characters and must also pass the sensitive
    filter; an entry is dropped if either value matches.  Returns the number
    of lines written.
    """
    if len(artifact_text) > MAX_ARTIFACT:
        return 0
    array = _last_json_array(artifact_text)
    if not array:
        return 0
    valid = []
    for entry in array:
        if not isinstance(entry, dict):
            continue
        ask_id = entry.get('ask_id')
        proposed = entry.get('proposed')
        if not isinstance(ask_id, str) or ask_id not in known_ids:
            continue
        if not isinstance(proposed, str) or not proposed.strip() or len(proposed) > MAX_PROPOSED:
            continue
        if SENSITIVE_RE.search(proposed):
            continue
        record = {'ask_id': ask_id, 'proposed': proposed}
        evidence = entry.get('evidence')
        if isinstance(evidence, str):
            evidence = evidence[:MAX_EVIDENCE]
            if SENSITIVE_RE.search(evidence):
                continue
            record['evidence'] = evidence
        valid.append(record)
    if not valid:
        return 0
    base = Path(tenants_dir).resolve()
    asks_dir = Path(tenants_dir) / tenant / 'asks'
    if asks_dir.is_symlink() or not asks_dir.resolve().is_relative_to(base):
        return 0
    asks_dir.mkdir(parents=True, exist_ok=True)
    path = asks_dir / 'proposed.jsonl'
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'a') as stream:
        for record in valid:
            stream.write(json.dumps(record) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return len(valid)


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
    known_ids = {ask['id'] for ask in (listing.get('asks') if isinstance(listing, dict) else [])
                 if isinstance(ask, dict) and isinstance(ask.get('id'), str)}
    count = import_proposals(tenants_dir, tenant, output, known_ids)
    print('Imported %d proposal(s)' % count)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
