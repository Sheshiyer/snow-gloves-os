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
import unicodedata

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
MAX_BLOB_BYTES = 512 * 1024 * 1024  # all file contents together; every task clones them
SCAN_SECONDS = 120
MAX_REFS = 10_000
MAX_CONFIG_BYTES = 64 * 1024  # .git/config of a tenant repository
MAX_GIT_ENTRIES = 2 * MAX_OBJECTS + 10_000  # files and directories under .git, loose objects included
MAX_ROOT_ENTRIES = 256  # top-level names in a tenant checkout (the layout allows about 16)
TENANT_LAYOUT = frozenset({'MANIFEST.yaml', 'README.md', '.gitignore', 'context', 'meristem', 'sources.yaml',
                           'enabled.yaml', 'runtime.yaml', 'ingest-plan.json', 'asks', 'wiki', 'history',
                           'documents', 'data', 'audit', 'tenants'})


# Repository-local Git config a tenant root may carry. Anything else (filter
# drivers, core.fsmonitor, core.hooksPath, include.path, diff/merge drivers...)
# can make the worker's own git add, checkout or apply run a command.
SAFE_CONFIG = re.compile(r'(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)'
                         r'|extensions\.objectformat|user\.(name|email)'
                         r'|remote\.[^.\s]+\.(url|fetch|tagopt)|branch\.[^.\s]+\.(remote|merge))')


# The only tree entry modes Git writes: folder, file, executable, symlink, submodule.
TREE_MODES = frozenset({b'40000', b'100644', b'100755', b'120000', b'160000'})

# Characters macOS (HFS+) ignores when comparing names, so ".g\u200cit" still means ".git".
_HFS_IGNORED = re.compile('[\u200c-\u200f\u202a-\u202e\u206a-\u206f\ufeff]')


def _folded(name):
    """*name* as a case-insensitive, normalization-insensitive macOS volume compares it."""
    return unicodedata.normalize('NFC', _HFS_IGNORED.sub('', name)).casefold()


def _valid_tree_name(name):
    """Whether Git would check out a tree entry named *name* (bytes). Names a checkout
    refuses (empty, ".", "..", a slash or backslash, any spelling of ".git") pass a
    --no-checkout clone but fail every task's checkout, so the scan refuses them."""
    if not name or name in (b'.', b'..') or b'/' in name or b'\\' in name:
        return False
    try:
        text = name.decode('utf-8')
    except UnicodeDecodeError:
        return True  # not a Unicode spelling of .git; Git checks out raw bytes
    folded = _HFS_IGNORED.sub('', text).rstrip(' .').lower()
    return folded != '.git' and folded != 'git~1'


def _unsafe_config(root, git_path='git'):
    """Repository-local config keys outside SAFE_CONFIG, or None when the config cannot be read."""
    config = os.path.join(str(root), '.git', 'config')
    if not os.path.lexists(config):
        return []
    # A tenant repository's config is a few hundred bytes; a larger one is refused before
    # Git reads it, so its listing (bounded by the file) can never flood the worker.
    try:
        info = os.lstat(config)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES:
        return None
    try:
        names = subprocess.run([git_path, 'config', '--file', config, '--no-includes', '--name-only', '--list'],
                               capture_output=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if len(names) > MAX_CONFIG_BYTES:
        return None
    return sorted({name for name in names.decode('utf-8', 'replace').split('\n') if name and not SAFE_CONFIG.fullmatch(name.lower())})


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


def _own_object_store(root, deadline=None):
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
    # could block or redirect Git's reads during the scan and the task. The walk shares
    # the scan's deadline and is capped in entries, so a huge .git fails closed.
    # Entries are read one at a time (os.scandir), never a whole directory listing at once,
    # so the cap bounds memory as well as time; an unreadable directory fails closed.
    deadline = time.monotonic() + SCAN_SECONDS if deadline is None else deadline
    seen, pending = 0, [git_dir]
    try:
        while pending:
            with os.scandir(pending.pop()) as listing:
                for entry in listing:
                    seen += 1
                    if seen > MAX_GIT_ENTRIES or time.monotonic() > deadline:
                        return False
                    mode = entry.stat(follow_symlinks=False).st_mode
                    if stat.S_ISDIR(mode):
                        pending.append(entry.path)
                    elif not stat.S_ISREG(mode):
                        return False
    except OSError:
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
    process = subprocess.Popen([git_path, '--no-replace-objects', '-C', str(root), 'cat-file', '--batch'],
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


def _refs_are_plain_commits(git_path, root, deadline):
    """True when every ref names a commit and none is a replacement ref, streamed under
    MAX_REFS and the scan deadline so a huge packed-refs file fails closed."""
    process = subprocess.Popen([git_path, '--no-replace-objects', '-C', str(root), 'for-each-ref',
                                '--format=%(objecttype) %(refname)'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    watchdog = _watchdog(process, deadline)
    try:
        for count, line in enumerate(process.stdout, 1):
            kind, _, name = line.rstrip(b'\n').partition(b' ')
            # A replace ref makes Git show a different object than the clone receives.
            if count > MAX_REFS or kind != b'commit' or name.startswith(b'refs/replace/') or time.monotonic() > deadline:
                return False
    finally:
        watchdog.cancel()
        process.kill()
        process.wait()
    return process.returncode in (0, -9) and time.monotonic() <= deadline


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
    deadline = time.monotonic() + SCAN_SECONDS
    if not _own_object_store(root, deadline):
        return None
    def git(*args):
        return subprocess.run([git_path, '--no-replace-objects', '-C', str(root), *args], capture_output=True, check=True, timeout=SCAN_SECONDS).stdout
    try:
        width = 32 if git('rev-parse', '--show-object-format').strip() == b'sha256' else 20
        # A clone transfers every ref; one naming a tag, tree or blob would carry objects
        # (a tag message, a tagged blob) that the commit-tree checks below never inspect.
        # Every command runs with replacements off, so the scan sees what a clone receives.
        if not _refs_are_plain_commits(git_path, root, deadline):
            return None
        # A task checks HEAD out; a root without a commit at HEAD has nothing to verify.
        if subprocess.run([git_path, '--no-replace-objects', '-C', str(root), 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}'],
                          capture_output=True, timeout=SCAN_SECONDS).returncode:
            return None
        wanted, sizes, count, metadata, commits, blob_bytes = [], {}, 0, 0, set(), 0
        listing = subprocess.Popen([git_path, '--no-replace-objects', '-C', str(root), 'cat-file', '--batch-all-objects',
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
                    if kind == b'commit':
                        commits.add(oid)
                elif kind == b'blob':
                    sizes[oid] = int(size)
                    blob_bytes += int(size)
                if (count > MAX_OBJECTS or metadata > MAX_METADATA_BYTES or blob_bytes > MAX_BLOB_BYTES
                        or time.monotonic() > deadline):
                    return None
        finally:
            watchdog.cancel()
            listing.kill()
            listing.wait()
        if listing.returncode not in (0, -9) or time.monotonic() > deadline:
            return None
        entries, roots, parents = {}, set(), set()
        for name, kind, body in _batch(git_path, root, wanted, deadline):
            if kind == b'commit':
                # Every commit must open with a canonical tree header. One without it never adds
                # a root here, so a valid commit elsewhere could pass the scan while a clone
                # rejects the repository as a bogus commit.
                header = re.match(rb'tree ([0-9a-f]{%d})\n' % (2 * width), body)
                if header is None:
                    return None
                roots.add(header.group(1))
                # Parent lines follow the tree line, and a clone walks every one of them; a
                # malformed one is as bogus to a clone as a missing header.
                cursor = header.end()
                while body.startswith(b'parent ', cursor):
                    parent = re.compile(rb'parent ([0-9a-f]{%d})\n' % (2 * width)).match(body, cursor)
                    if parent is None:
                        return None
                    parents.add(parent.group(1))
                    cursor = parent.end()
                continue
            children, folded, cursor = {}, set(), 0
            while cursor < len(body):
                space = body.index(b' ', cursor)
                nul = body.index(b'\0', space)
                name_bytes = body[space + 1:nul]
                # Git reads zero-padded modes such as 040000 or 0120000 as folders and links;
                # only the canonical spellings are classified below, so refuse any other.
                if body[cursor:space] not in TREE_MODES:
                    return None
                if not _valid_tree_name(name_bytes):
                    return None
                # A malformed tree naming an entry twice would hide one copy from this scan
                # while a clone still carries both; refuse it.
                if name_bytes in children:
                    return None
                # Two siblings differing only in case or Unicode normalization (Foo.md, foo.md) are
                # one path on a case-insensitive Mac: checkout keeps one, not the tree verified here.
                key = _folded(name_bytes.decode('utf-8', 'replace'))
                if key in folded:
                    return None
                folded.add(key)
                children[name_bytes] = (body[cursor:space], body[nul + 1:nul + 1 + width].hex().encode())
                cursor = nul + 1 + width
            entries[name] = children
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    # Every tree a commit or tree points at, and every file a tree lists, must be present:
    # a missing one passes as empty here, while a clone or checkout of it fails.
    for children in entries.values():
        for mode, oid in children.values():
            if (mode == b'40000' and oid not in entries) or (mode in (b'100644', b'100755', b'120000') and oid not in sizes):
                return None
    # A missing (or non-commit) parent passes here, but the clone that walks it fails.
    if roots - entries.keys() or parents - commits:
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
    owners, blobs = set(), {}  # dict: O(1) dedupe, insertion order kept for the batch
    for root_tree in roots:
        if time.monotonic() > deadline:
            return None
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
        else:
            blobs[oid] = None
    try:
        for _, _, body in _batch(git_path, root, list(blobs), deadline):
            owners.add(_manifest_tenant(body))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    # The checks above trust each object's name. A full fsck rehashes every object, so one
    # stored under another object's name (which a clone rejects) also fails the scan. It runs
    # last, inside the same deadline; its output is discarded and only its status counts.
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        checked = subprocess.run([git_path, '--no-replace-objects', '-C', str(root), 'fsck', '--full', '--strict',
                                  '--no-dangling', '--no-progress'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=remaining)
    except (OSError, subprocess.SubprocessError):
        return None
    if checked.returncode:
        return None
    return tenants, top, links, names, owners


def isolation_problem(root, tenant, git_path='git'):
    """Why *root* is not a tenant-only repository for *tenant*, or None when it is."""
    # The config goes first, read without includes: every later Git command would follow an
    # include (one naming a FIFO could block it for its whole timeout) or run what it names.
    unsafe = _unsafe_config(root, git_path)
    if unsafe is None:
        return 'Cannot read the Git config of project root %s; use a standalone tenant repository' % root
    if unsafe:
        return ('Project root %s has Git config that could run commands (%s); use a tenant-only repository with default config'
                % (root, ', '.join(unsafe)))
    layout = git_layout(root, git_path)
    if layout is None:
        return 'Cannot verify the Git history of project root %s; use a standalone tenant repository' % root
    found, top, links, names, owners = layout
    if found - {tenant}:
        return 'Project root %s has other tenants in its Git history; use a tenant-only repository' % root
    # A worker checks the tree out, so a tracked link could lead its task out of the root.
    if links:
        return 'Project root %s tracks a symlink or submodule; use a tenant-only repository without links' % root
    # Read one entry at a time under a cap: a tenant root holds a handful of TENANT_LAYOUT
    # names, so a huge listing (untracked junk) is refused before it fills memory.
    checked_out = set()
    try:
        with os.scandir(root) as listing:
            for entry in listing:
                if entry.name != '.git':
                    checked_out.add(entry.name)
                    if len(checked_out) > MAX_ROOT_ENTRIES:
                        return ('Project root %s has more than %d top-level entries; use a tenant-only repository'
                                % (root, MAX_ROOT_ENTRIES))
    except OSError:
        return 'Cannot read project root %s; use a standalone tenant repository' % root
    # Fleet, node, audit, planning and spec files hold every tenant's state, at any depth
    # (backup/fleet.yaml is as readable as fleet.yaml).
    # Compared case-folded and normalized: on a case-insensitive Mac, context/FLEET.YAML or
    # context/Nodes is the same shared data as fleet.yaml or nodes.
    shared = sorted(name for name in names | checked_out if _folded(name) in SHARED_INSTANCE_PATHS)
    if shared:
        return 'Project root %s holds shared instance data (%s); use a tenant-only repository' % (root, ', '.join(shared))
    # The top level must look like one tenant's folder, so renamed copies of shared
    # state cannot sit beside it unnoticed.
    unexpected = sorted((top | checked_out) - TENANT_LAYOUT)
    if unexpected:
        return ('Project root %s has entries outside the tenant layout (%s); use a tenant-only repository'
                % (root, ', '.join(unexpected)))
    # Every commit with content must be this tenant's (a repository reused from another
    # tenant keeps that tenant's files readable through its history), and at least one
    # must be: empty commits alone carry no tenant manifest or context at all.
    if owners - {tenant} or tenant not in owners:
        return ('Project root %s has commits whose MANIFEST.yaml does not name %s, or none that does; use a repository '
                'with only this tenant\'s history' % (root, tenant))
    return None
