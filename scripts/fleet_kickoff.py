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
DEFAULT_WAVE = '2026-10-16'


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
    if len(brief) <= MAX_BRIEF:
        return brief
    truncated = brief[:MAX_BRIEF]
    last_nl = truncated.rfind('\n')
    if last_nl != -1:
        truncated = truncated[:last_nl]
    return truncated


def _task_body(project, tenant, brief, wave):
    return {
        'project': project,
        'title': 'Kickoff research: ' + tenant,
        'brief': brief,
        # Root commercial-preparation tasks require an admitted business context;
        # kickoff research is a plain read-only task.
        'category': 'development',
        'access': 'read',
        'idempotency_key': 'kickoff-%s-%s' % (project, wave),
    }


def _list_asks(coordinator, token, project):
    request = urllib.request.Request(
        coordinator.rstrip('/') + '/v1/asks/' + project,
        headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            asks = json.load(response).get('asks', [])
            return asks if isinstance(asks, list) else []
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _submit_task(coordinator, token, project, tenant, brief, wave):
    body = _task_body(project, tenant, brief, wave)
    request = urllib.request.Request(
        coordinator.rstrip('/') + '/v1/tasks',
        data=json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(json.dumps(json.load(response), indent=2))
    except urllib.error.HTTPError as exc:
        return 'kickoff failed: HTTP %d' % exc.code
    except (urllib.error.URLError, OSError):
        return 'kickoff failed: coordinator unavailable'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coordinator', required=True)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--projects', required=True)
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--wave', default=DEFAULT_WAVE)
    args = parser.parse_args()
    token = Path(args.token_file).read_text().strip()
    projects = [p.strip() for p in args.projects.split(',') if p.strip()]
    failed = False
    for project in projects:
        asks = _list_asks(args.coordinator, token, project)
        if asks is None:
            print('warning: could not list asks for project %s' % project, file=sys.stderr)
            failed = True
            continue
        if not asks:
            continue
        tenant = asks[0].get('tenant', project)
        brief = kickoff_brief(tenant, asks)
        if args.submit:
            err = _submit_task(args.coordinator, token, project, tenant, brief, args.wave)
            if err:
                print('warning: %s (project: %s)' % (err, project), file=sys.stderr)
                failed = True
        else:
            print(brief)
            print('---')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
