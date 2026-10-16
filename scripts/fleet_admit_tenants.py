#!/usr/bin/env python3
"""Admit tenants as read-only coordinator projects keyed by the tenant slug."""
import argparse
import copy
import json
import sys
from pathlib import Path


def admit(config, tenants, organization, principal, workers):
    """Return a new config with each tenant admitted as a read-only codex project.

    An existing project already mapped to a tenant is left untouched.  New
    project ids are appended to the principal's and each listed worker's
    projects.  No write, fanout or write_projects grant is ever set.
    """
    result = copy.deepcopy(config)
    projects = result.setdefault('projects', {})
    existing_tenants = {p.get('tenant') for p in projects.values()
                        if isinstance(p, dict) and isinstance(p.get('tenant'), str)}
    for tenant in tenants:
        if tenant in projects or tenant in existing_tenants:
            continue
        projects[tenant] = {'tenant': tenant, 'organization': organization, 'runtimes': ['codex']}
        principal_entry = result.get('principals', {}).get(principal)
        if isinstance(principal_entry, dict):
            principal_projects = principal_entry.setdefault('projects', [])
            if tenant not in principal_projects:
                principal_projects.append(tenant)
        for name in workers:
            worker_entry = result.get('workers', {}).get(name)
            if isinstance(worker_entry, dict):
                worker_projects = worker_entry.setdefault('projects', [])
                if tenant not in worker_projects:
                    worker_projects.append(tenant)
    return result


def _diff(old, new):
    old_pids = set(old.get('projects', {}))
    new_projects = new.get('projects', {})
    added = {pid: new_projects[pid] for pid in new_projects if pid not in old_pids}
    return {'added_projects': added}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--tenants', required=True)
    parser.add_argument('--organization', required=True)
    parser.add_argument('--principal', required=True)
    parser.add_argument('--workers', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    tenants = [t.strip() for t in args.tenants.split(',') if t.strip()]
    workers = [w.strip() for w in args.workers.split(',') if w.strip()]
    new_config = admit(config, tenants, args.organization, args.principal, workers)
    if args.write:
        path = Path(args.config)
        path.write_text(json.dumps(new_config, indent=2))
        path.chmod(0o600)
        return 0
    print(json.dumps(_diff(config, new_config), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
