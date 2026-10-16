#!/usr/bin/env python3
"""Admit tenants as read-only coordinator projects keyed by the tenant slug."""
import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')


def admit(config, tenants, organization, principal, workers, root=None):
    """Return a new config with each tenant admitted as a read-only codex project.

    An existing project already mapped to a tenant is left untouched.  New
    project ids are appended to the principal's and each listed worker's
    projects.  No write, fanout or write_projects grant is ever set.

    The coordinator refuses to start when a project served by a local worker
    has no absolute Git root, so *root* is required whenever any listed worker
    is local (not enrolled with ``remote_artifacts: true``).
    """
    if not isinstance(organization, str) or not organization.strip():
        raise ValueError('Project organization must be a non-empty string')
    if not workers:
        raise ValueError('At least one worker is required; a project without workers is treated as local and needs a root')
    if not isinstance(config.get('principals', {}).get(principal), dict):
        raise ValueError('Unknown principal: %s' % principal)
    unknown = [name for name in workers if not isinstance(config.get('workers', {}).get(name), dict)]
    if unknown:
        raise ValueError('Unknown worker: %s' % ', '.join(unknown))
    local = [name for name in workers
             if isinstance(config.get('workers', {}).get(name), dict)
             and config['workers'][name].get('remote_artifacts') is not True]
    if root is not None and (not isinstance(root, str) or not os.path.isabs(root)):
        raise ValueError('Project root must be an absolute path')
    # Same invariant load_config() enforces, checked before any config is written.
    if root is not None and (not os.path.isdir(root) or not os.path.exists(os.path.join(root, '.git'))):
        raise ValueError('Project root must be an existing Git checkout: %s' % root)
    # The asks API, proxy and UI route project ids as [a-z0-9][a-z0-9_-]{0,63}.
    unroutable = [t for t in tenants if not isinstance(t, str) or not PROJECT_ID.fullmatch(t)]
    if unroutable:
        raise ValueError('Tenant slug is not a routable project id: %s' % ', '.join(map(str, unroutable)))
    if local and root is None:
        raise ValueError('A project root is required when admitting tenants to local workers: %s' % ', '.join(local))
    result = copy.deepcopy(config)
    projects = result.setdefault('projects', {})
    existing_tenants = {p.get('tenant') for p in projects.values()
                        if isinstance(p, dict) and isinstance(p.get('tenant'), str)}
    for tenant in tenants:
        if tenant in projects and (not isinstance(projects[tenant], dict) or projects[tenant].get('tenant') != tenant):
            raise ValueError('Project id %s already maps to a different tenant' % tenant)
        if tenant in projects or tenant in existing_tenants:
            continue
        projects[tenant] = {'tenant': tenant, 'organization': organization, 'runtimes': ['codex']}
        if root is not None:
            projects[tenant]['root'] = root
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


def _write_config(path, config):
    """Atomically write *config* to *path* with mode 0600 from creation.

    The config file holds principal tokens, so it is written to a temp file in
    the same directory opened with O_CREAT|O_EXCL at 0600, fsynced, then
    os.replace'd onto the target.  There is never a moment where the file
    exists with broader permissions.
    """
    path = Path(path)
    data = json.dumps(config, indent=2).encode('utf-8')
    tmp_path = path.with_name('.' + path.name + '.tmp.%d' % os.getpid())
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp_path), str(path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--tenants', required=True)
    parser.add_argument('--organization', required=True)
    parser.add_argument('--principal', required=True)
    parser.add_argument('--workers', required=True)
    parser.add_argument('--root', help='absolute Git checkout for the new projects; required for local workers')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    tenants = [t.strip() for t in args.tenants.split(',') if t.strip()]
    workers = [w.strip() for w in args.workers.split(',') if w.strip()]
    try:
        new_config = admit(config, tenants, args.organization, args.principal, workers, root=args.root)
    except ValueError as exc:
        print('error: %s' % exc, file=sys.stderr)
        sys.exit(2)
    if args.write:
        _write_config(Path(args.config), new_config)
        return 0
    print(json.dumps(_diff(config, new_config), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
