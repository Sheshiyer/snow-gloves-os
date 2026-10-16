#!/usr/bin/env python3
"""Generate and submit read-only research kickoff tasks for tenant fact asks."""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

MAX_ASKS = 40
MAX_BRIEF = 16000


def kickoff_brief(tenant, asks):
    """Build a brief listing up to 40 open fact asks for a read-only research task."""
    fact_asks = [a for a in asks if isinstance(a, dict)
                 and a.get('kind') == 'fact' and a.get('status') == 'open']
    lines = ['- %s: %s (%s)' % (a.get('id', ''), a.get('title', ''), a.get('source', ''))
             for a in fact_asks[:MAX_ASKS]]
    brief = (
        'Research %s\'s open fact asks and propose values.\n\n'
        'Use only the tenant\'s own context files, public sources and Meristem outputs. '
        'Do not use credentials, connectors or external paths. Do not write to any file.\n\n'
        'Open fact asks (up to %d):\n%s\n\n'
        'Return a JSON array of objects with keys "ask_id", "proposed" and "evidence". '
        'Omit any ask for which you have no evidence. '
        'Each proposed value must be 500 characters or fewer.'
        % (tenant, MAX_ASKS, '\n'.join(lines)))
    return brief[:MAX_BRIEF]


def _list_asks(coordinator, token, project):
    request = urllib.request.Request(
        coordinator.rstrip('/') + '/v1/asks/' + project,
        headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response).get('asks', [])
    except (urllib.error.URLError, OSError, ValueError):
        return []


def _submit_task(coordinator, token, project, tenant, brief):
    body = {
        'project': project,
        'title': 'Kickoff research: ' + tenant,
        'brief': brief,
        'category': 'commercial-preparation',
        'access': 'read',
        'idempotency_key': 'kickoff-%s-2026-10-16' % project,
    }
    request = urllib.request.Request(
        coordinator.rstrip('/') + '/v1/tasks',
        data=json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(json.dumps(json.load(response), indent=2))
    except urllib.error.HTTPError as exc:
        print('Kickoff failed: HTTP ' + str(exc.code), file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError):
        print('Fleet coordinator unavailable', file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coordinator', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--projects', required=True)
    parser.add_argument('--submit', action='store_true')
    args = parser.parse_args()
    token = Path(args.token_file).read_text().strip()
    projects = [p.strip() for p in args.projects.split(',') if p.strip()]
    for project in projects:
        asks = _list_asks(args.coordinator, token, project)
        if not asks:
            continue
        tenant = asks[0].get('tenant', project)
        brief = kickoff_brief(tenant, asks)
        if args.submit:
            rc = _submit_task(args.coordinator, token, project, tenant, brief)
            if rc:
                return rc
        else:
            print(brief)
            print('---')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
