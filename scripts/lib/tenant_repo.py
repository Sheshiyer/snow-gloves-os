"""Tenant-only Git repositories: the isolation check run at admission and before every task.

A worker gives each task a linked worktree of the project root, so every object
in the root's database is readable (git show, cat-file), not just the files
checked out. A tenant root must therefore hold, anywhere in its history, no
other tenant, no shared instance data and no link that leads out of it.
"""
import os
import re
import stat
import subprocess
import threading
import time

from .cockpit_tenant_map import strict_yaml

# Instance data the private checkout keeps beside tenants/ (see scripts/lib/paths.py):
# fleet inventory, node profiles, audit receipts, planning state and portfolio specs.
SHARED_INSTANCE_PATHS = frozenset({'fleet.yaml', 'nodes', '_audit', '.planning', 'specs'})
# What a tenant folder holds (tenants/<slug>/ in the private checkout), plus a README
# and an optional tenants/<slug>/ wrapper. Anything else at a tenant root is refused.
MAX_MANIFEST = 256 * 1024
# A tenant repository is small; anything past these fails the check closed rather than
# letting a pre-task scan exhaust the worker's memory or time.
MAX_OBJECTS = 200_000
MAX_METADATA_BYTES = 64 * 1024 * 1024  # all commit and tree bodies together
SCAN_SECONDS = 120
TENANT_LAYOUT = frozenset({'MANIFEST.yaml', 'README.md', '.gitignore', 'context', 'meristem', 'sources.yaml',
                           'enabled.yaml', 'runtime.yaml', 'ingest-plan.json', 'asks', 'wiki', 'history',
                           'documents', 'data', 'audit', 'tenants'})


# Repository-local Git config a tenant root may carry. Anything else (filter
# drivers, core.fsmonitor, core.hooksPath, include.path, diff/merge drivers...)
# can make the worker's own git add, checkout or apply run a command.
SAFE_CONFIG = re.compile(r'(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)'
                         r'|extensions\.objectformat|user\.(name|email)'
                         r'|remote\.[^.\s]+\.(url|fetch|tagopt)|branch\.[^.\s]+\.(remote|merge))')


def _unsafe_config(root, git_path='git'):
    """Repository-local config keys outside SAFE_CONFIG, or None when the config cannot be read."""
    config = os.path.join(str(root), '.git', 'config')
    if not os.path.lexists(config):
        return []
    try:
        names = subprocess.run([git_path, 'config', '--file', config, '--no-includes', '--name-only', '--list'],
                               capture_output=True, check=True, timeout=30).stdout.decode('utf-8', 'replace').split('\n')
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted({name for name in names if name and not SAFE_CONFIG.fullmatch(name.lower())})


def _manifest_tenant(raw):
    """The tenant a MANIFEST.yaml names, parsed with the strict reader (no duplicate keys
    or aliases), or None when it is too large, malformed or names no tenant."""
    if len(raw) > MAX_MANIFEST:
        return None
    try:
        value = strict_yaml(raw)
    except Exception:  # any parse failure means the commit's owner is unknown
        return None
    tenant = value.get('tenant') if isinstance(value, dict) else None
    return tenant if isinstance(tenant, str) else None


def _own_object_store(root):
    """True when .git and its object store are real directories inside *root*.

    A .git file or link, any link or special file inside .git (objects, shards,
    packs), a commondir file or an alternates list would all let this root read
    another repository's objects or stall the scan.
    """
    root = os.path.realpath(str(root))
    git_dir = os.path.join(root, '.git')
    objects = os.path.join(git_dir, 'objects')
    for path in (git_dir, objects, os.path.join(objects, 'pack'), os.path.join(objects, 'info')):
        if os.path.islink(path) or (path in (git_dir, objects) and not os.path.isdir(path)):
            return False
    if os.path.lexists(os.path.join(git_dir, 'commondir')) or os.path.lexists(os.path.join(objects, 'info', 'alternates')):
        return False
    if os.path.realpath(objects) != objects or os.path.dirname(os.path.realpath(git_dir)) != root:
        return False
    # Git follows a link anywhere in its metadata (a loose-object shard, a pack
    # file), so one link inside .git is enough to borrow foreign objects.
    # Only real directories and regular files: a FIFO, socket or device inside .git
    # could block or redirect Git's reads during the scan and the task.
    for directory, subdirs, files in os.walk(git_dir, followlinks=False):
        for name in subdirs + files:
            mode = os.lstat(os.path.join(directory, name)).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                return False
    return True


def _watchdog(process, deadline):
    """Kill *process* at *deadline*, so a read blocked on it ends (EOF) instead of hanging."""
    timer = threading.Timer(max(0.0, deadline - time.monotonic()), process.kill)
    timer.daemon = True
    timer.start()
    return timer


def _batch(git_path, root, oids, deadline):
    """Stream (oid, type, body) for *oids* from one cat-file --batch, never buffering the
    whole output; the input is fed from a thread so neither pipe can fill and stall."""
    process = subprocess.Popen([git_path, '-C', str(root), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    watchdog = _watchdog(process, deadline)
    def feed():
        try:
            for oid in oids:
                process.stdin.write(oid + b'\n')
            process.stdin.close()
        except OSError:
            pass
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    try:
        for _ in oids:
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired('git cat-file', SCAN_SECONDS)
            header = process.stdout.readline().split()
            if time.monotonic() > deadline or len(header) != 3:
                raise subprocess.SubprocessError('unexpected cat-file output')
            body = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            yield header[0], header[1], body
    finally:
        watchdog.cancel()
        process.kill()
        process.wait()
        writer.join(1)


def git_layout(root, git_path='git'):
    """Tenant names under any tenants/ tree, every top-level name any commit has held,
    whether any tree records a symlink or submodule (either can reach outside the root),
    every entry name at any depth of any tree, and the tenant each commit's root
    MANIFEST.yaml (or the sole tenants/<slug>/MANIFEST.yaml) names (None for a commit
    with content but no readable manifest).

    Workers get a linked worktree of this repository, so any object in it is
    readable (git show, cat-file), not just the checked-out files. Returns None
    when the database cannot be fully enumerated, borrows objects elsewhere, or is
    larger than a tenant repository may be (MAX_OBJECTS, MAX_METADATA_BYTES): the
    check then fails closed instead of exhausting the worker.
    """
    if not _own_object_store(root):
        return None
    deadline = time.monotonic() + SCAN_SECONDS
    def git(*args):
        return subprocess.run([git_path, '-C', str(root), *args], capture_output=True, check=True, timeout=SCAN_SECONDS).stdout
    try:
        width = 32 if git('rev-parse', '--show-object-format').strip() == b'sha256' else 20
        # A clone transfers every ref; one naming a tag, tree or blob would carry objects
        # (a tag message, a tagged blob) that the commit-tree checks below never inspect.
        ref_types = git('for-each-ref', '--format=%(objecttype)').split()
        if any(kind != b'commit' for kind in ref_types):
            return None
        wanted, sizes, count, metadata = [], {}, 0, 0
        listing = subprocess.Popen([git_path, '-C', str(root), 'cat-file', '--batch-all-objects',
                                    '--batch-check=%(objecttype) %(objectname) %(objectsize)'],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        watchdog = _watchdog(listing, deadline)
        try:
            for line in listing.stdout:
                count += 1
                kind, oid, size = line.split()
                if kind in (b'tree', b'commit'):
                    wanted.append(oid)
                    metadata += int(size)
                elif kind == b'blob':
                    sizes[oid] = int(size)
                if count > MAX_OBJECTS or metadata > MAX_METADATA_BYTES or time.monotonic() > deadline:
                    return None
        finally:
            watchdog.cancel()
            listing.kill()
            listing.wait()
        if listing.returncode not in (0, -9) or time.monotonic() > deadline:
            return None
        entries, roots = {}, set()
        for name, kind, body in _batch(git_path, root, wanted, deadline):
            if kind == b'commit':
                if body.startswith(b'tree '):
                    roots.add(body[5:body.index(b'\n')])
                continue
            children, cursor = {}, 0
            while cursor < len(body):
                space = body.index(b' ', cursor)
                nul = body.index(b'\0', space)
                children[body[space + 1:nul]] = (body[cursor:space], body[nul + 1:nul + 1 + width].hex().encode())
                cursor = nul + 1 + width
            entries[name] = children
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    tenants = set()
    for children in entries.values():
        mode, oid = children.get(b'tenants', (None, None))
        if mode == b'40000':
            tenants.update(child.decode('utf-8', 'replace') for child in entries.get(oid, {}))
    top = {child.decode('utf-8', 'replace') for root_tree in roots for child in entries.get(root_tree, {})}
    links = any(mode in (b'120000', b'160000') for children in entries.values() for mode, _ in children.values())
    names = {child.decode('utf-8', 'replace') for children in entries.values() for child in children}
    # Who each commit belongs to: the tenant named by its root MANIFEST.yaml, or None when
    # a commit with content has no readable manifest (it could be another tenant's).
    owners, blobs = set(), []
    for root_tree in roots:
        children = entries.get(root_tree, {})
        if not children:
            continue
        mode, oid = children.get(b'MANIFEST.yaml', (None, None))
        wrapper_mode, wrapper = children.get(b'tenants', (None, None))
        if mode is None and wrapper_mode == b'40000' and len(entries.get(wrapper, {})) == 1:
            # The tenants/<slug>/ layout: the sole wrapped folder's manifest names the owner.
            (inner_mode, inner), = entries[wrapper].values()
            if inner_mode == b'40000':
                mode, oid = entries.get(inner, {}).get(b'MANIFEST.yaml', (None, None))
        # An oversized manifest is never fetched; its owner is unknown.
        if mode not in (b'100644', b'100755') or sizes.get(oid, MAX_MANIFEST + 1) > MAX_MANIFEST:
            owners.add(None)
        elif oid not in blobs:
            blobs.append(oid)
    try:
        for _, _, body in _batch(git_path, root, blobs, deadline):
            owners.add(_manifest_tenant(body))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return tenants, top, links, names, owners


def isolation_problem(root, tenant, git_path='git'):
    """Why *root* is not a tenant-only repository for *tenant*, or None when it is."""
    layout = git_layout(root, git_path)
    if layout is None:
        return 'Cannot verify the Git history of project root %s; use a standalone tenant repository' % root
    found, top, links, names, owners = layout
    unsafe = _unsafe_config(root, git_path)
    if unsafe is None:
        return 'Cannot read the Git config of project root %s; use a standalone tenant repository' % root
    if unsafe:
        return ('Project root %s has Git config that could run commands (%s); use a tenant-only repository with default config'
                % (root, ', '.join(unsafe)))
    if found - {tenant}:
        return 'Project root %s has other tenants in its Git history; use a tenant-only repository' % root
    # A worker checks the tree out, so a tracked link could lead its task out of the root.
    if links:
        return 'Project root %s tracks a symlink or submodule; use a tenant-only repository without links' % root
    checked_out = set(os.listdir(root)) - {'.git'}
    # Fleet, node, audit, planning and spec files hold every tenant's state, at any depth
    # (backup/fleet.yaml is as readable as fleet.yaml).
    shared = sorted((names | checked_out) & SHARED_INSTANCE_PATHS)
    if shared:
        return 'Project root %s holds shared instance data (%s); use a tenant-only repository' % (root, ', '.join(shared))
    # The top level must look like one tenant's folder, so renamed copies of shared
    # state cannot sit beside it unnoticed.
    unexpected = sorted((top | checked_out) - TENANT_LAYOUT)
    if unexpected:
        return ('Project root %s has entries outside the tenant layout (%s); use a tenant-only repository'
                % (root, ', '.join(unexpected)))
    # Every commit with content must be this tenant's: a repository reused from another
    # tenant keeps that tenant's files readable through its history.
    if owners - {tenant}:
        return ('Project root %s has commits whose MANIFEST.yaml does not name %s; use a repository with only this tenant\'s history'
                % (root, tenant))
    return None
