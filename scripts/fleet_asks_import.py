#!/usr/bin/env python3
"""Import agent research proposals into a tenant's ask proposal journal."""
import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
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
IMPORTED = 'imported'  # asks/imported/<sha256(source)>: tasks that finished importing
COMPACT_AT = 4 * 1024 * 1024  # past this, the journal is rewritten to its live records
MAX_COMPACT_BYTES = 64 * 1024 * 1024
MAX_COMPACT_RECORDS = 1_000_000
COMPACT_SECONDS = 30
MAX_MARKERS_PER_COMPACT = 1000  # legacy completion lines moved to marker files per compaction
# Compaction never waits past this size, half the listing's scan budget, so live
# proposals always stay readable by every ask listing.
MAX_COMPACT_TRIGGER = 16 * 1024 * 1024
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
        except (ValueError, json.JSONDecodeError, RecursionError):
            # A candidate nested too deep for the decoder is skipped like any malformed one.
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
    retried. Returns None past the byte or time budget (an unscannable journal). Lines written before completion lines existed (no ``created`` key)
    came from one fsynced write and count as complete.
    """
    latest, done = {}, False
    stream.seek(0)
    deadline, scanned = time.monotonic() + COMPACT_SECONDS, 0
    while True:
        line = stream.readline(MAX_JOURNAL_LINE + 1)
        scanned += len(line)
        if not line:
            break
        if len(line) > MAX_JOURNAL_LINE:
            while line and not line.endswith(b'\n'):
                line = stream.readline(MAX_JOURNAL_LINE)
                scanned += len(line)
                if scanned > MAX_COMPACT_BYTES or time.monotonic() > deadline:
                    return None
            continue
        # Past the budget the dedupe state is unknown: refuse the import rather than guess.
        if scanned > MAX_COMPACT_BYTES or time.monotonic() > deadline:
            return None
        try:
            record = json.loads(line.decode('utf-8', errors='replace'))
        except (ValueError, RecursionError):  # a nested-too-deep line is skipped like any bad one
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


def _open_regular(name, flags, dir_fd, mode=0o600):
    """Open *name* in the held asks directory without blocking or following a link, and
    refuse anything but a regular file: a FIFO planted under a known name would otherwise
    block the open (or a later read) while the tenant's journal lock is held."""
    fd = os.open(name, flags | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0), mode, dir_fd=dir_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(errno.EINVAL, 'Not a regular file', name)
    return fd


def _locked_journal(asks):
    """The journal opened in the held asks directory and locked, retrying if compaction
    replaced the file between our open and our lock."""
    while True:
        fd = _open_regular(JOURNAL, os.O_APPEND | os.O_CREAT | os.O_RDWR, asks)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            if os.fstat(fd).st_ino == os.stat(JOURNAL, dir_fd=asks, follow_symlinks=False).st_ino:
                return fd
        except FileNotFoundError:
            pass
        os.close(fd)


def _marker(source):
    return hashlib.sha256(source.encode('utf-8', 'surrogatepass')).hexdigest()


def _imported_dir(asks, create=False):
    """The held asks/imported/ directory (one marker file per fully imported source)."""
    directory = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    if create:
        try:
            os.mkdir(IMPORTED, 0o700, dir_fd=asks)
        except FileExistsError:
            pass
    return os.open(IMPORTED, directory, dir_fd=asks)


def _source_done(asks, source):
    """Whether *source* has a completion marker: one stat, however many tasks came before."""
    try:
        held = _imported_dir(asks)
    except FileNotFoundError:
        return False
    try:
        return stat.S_ISREG(os.stat(_marker(source), dir_fd=held, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False
    finally:
        os.close(held)


def _mark_imported(asks, sources, deadline=None):
    """Record each of *sources* ({source: created}) as fully imported, durably. With a
    *deadline*, stop once it passes; returns the sources recorded."""
    held = _imported_dir(asks, create=True)
    marked = set()
    try:
        for source, when in sources.items():
            if deadline is not None and marked and time.monotonic() > deadline:
                break
            # A FIFO planted under a marker's name is refused, never waited on, before truncation.
            fd = _open_regular(_marker(source), os.O_WRONLY | os.O_CREAT, held)
            try:
                os.ftruncate(fd, 0)
                os.write(fd, json.dumps({'source': source, 'created': when, 'complete': True}).encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            marked.add(source)
        os.fsync(held)
    finally:
        os.close(held)
    return marked


def _compacted_size(asks):
    """The journal size right after the last compaction, from a small marker file (0 if none)."""
    try:
        fd = _open_regular(JOURNAL + '.compacted', os.O_RDONLY, asks)
    except OSError:
        return 0  # missing, or not a regular file: compact as if never compacted
    try:
        value = os.read(fd, 32).strip()
        return int(value) if value.isdigit() else 0
    finally:
        os.close(fd)


def _record_compacted_size(asks, size):
    fd = _open_regular(JOURNAL + '.compacted', os.O_WRONLY | os.O_CREAT, asks)
    try:
        os.ftruncate(fd, 0)  # only once it is known to be a regular file
        os.write(fd, str(size).encode())
    finally:
        os.close(fd)


def _compact(stream, asks, current_ids=None):
    """Rewrite a large journal to the latest proposal per ask plus one completion line per
    imported source, so every later scan (each ask listing reads it) stays small.

    Runs under the journal lock; the new file replaces the old atomically, and waiting
    importers notice the replacement and reopen. Reading is capped in bytes, records,
    line length and time; past any cap the journal is left unchanged. Returns False when
    it did not compact, True when it did, and 'partial' when legacy completion lines are
    still left to move to marker files. With *current_ids* (every ask the tenant has now) only their
    proposals are kept.
    """
    latest, done = {}, {}
    stream.seek(0)
    deadline, scanned, records = time.monotonic() + COMPACT_SECONDS, 0, 0
    while True:
        line = stream.readline(MAX_JOURNAL_LINE + 1)
        if not line:
            break
        scanned += len(line)
        records += 1
        # Fail safe: past any budget, keep the journal as it is rather than hold it all.
        if scanned > MAX_COMPACT_BYTES or records > MAX_COMPACT_RECORDS or time.monotonic() > deadline:
            return False
        if len(line) > MAX_JOURNAL_LINE:
            while line and not line.endswith(b'\n'):
                line = stream.readline(MAX_JOURNAL_LINE)
                scanned += len(line)
                # The same budgets hold while the rest of an oversized line is discarded.
                if scanned > MAX_COMPACT_BYTES or time.monotonic() > deadline:
                    return False
            continue
        try:
            record = json.loads(line.decode('utf-8', errors='replace'))
        except (ValueError, RecursionError):  # a nested-too-deep line is skipped like any bad one
            continue
        if not isinstance(record, dict):
            continue
        if isinstance(record.get('ask_id'), str) and isinstance(record.get('proposed'), str):
            latest.pop(record['ask_id'], None)
            # Proposals for asks that no longer exist are dropped, so the journal tracks the
            # tenant's current asks rather than every id it ever had.
            if current_ids is None or record['ask_id'] in current_ids:
                latest[record['ask_id']] = record
        if isinstance(record.get('source'), str) and (record.get('complete') is True or 'created' not in record):
            done[record['source']] = _task_time(record.get('created'))
    # Completion lines move to per-source markers first, so the journal keeps only live
    # proposals and every listing reads them within its budget. A crash in between leaves
    # duplicate completion lines, which are harmless. Each pass moves a bounded batch within
    # the time budget; the rest stay as completion lines for the next compaction.
    marked = set()
    if done:
        batch = dict(list(done.items())[:MAX_MARKERS_PER_COMPACT])
        marked = _mark_imported(asks, batch, deadline)
    left = [{'source': source, 'created': when, 'complete': True} for source, when in done.items() if source not in marked]
    body = b''.join(json.dumps(record).encode() + b'\n' for record in [*latest.values(), *left])
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
    return 'partial' if left else True


def import_proposals(tenants_dir, tenant, artifact_text, known_ids, source=None, created=None, current_ids=None):
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
            scan = _scan_journal(stream, {record['ask_id'] for record in valid}, source)
            if scan is None:
                return 0
            recorded, imported = scan
            if not imported and source is not None:
                imported = _source_done(asks, source)
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
            if rows:
                size = os.fstat(stream.fileno()).st_size
                # A torn last line would swallow the first new record; end it first.
                lines = [b''] if size and os.pread(stream.fileno(), 1, size - 1) != b'\n' else []
                lines += [json.dumps(record).encode() for record in rows]
                stream.write(b'\n'.join(lines) + b'\n')
                stream.flush()
                os.fsync(stream.fileno())
            # Every task ends with a completion marker, written after its proposals reached
            # disk, so an interrupted import is retried; listings never read the markers.
            if source is not None:
                _mark_imported(asks, {source: created})
            # Compact only once the journal has doubled since its last compaction: live records
            # (one completion line per task) can keep it above COMPACT_AT, and re-reading it on
            # every import would make each import slower than the last.
            if os.fstat(stream.fileno()).st_size > max(COMPACT_AT, min(2 * _compacted_size(asks), MAX_COMPACT_TRIGGER)):
                try:
                    # None means the listing was unavailable (keep everything); an empty set is a
                    # listing with no asks, whose stale proposals are dropped like any others.
                    compacted = _compact(stream, asks, current_ids)
                    if compacted:
                        # With legacy completion lines still to move, let the next import compact
                        # again rather than wait for the journal to double.
                        size = os.stat(JOURNAL, dir_fd=asks, follow_symlinks=False).st_size
                        _record_compacted_size(asks, size if compacted is True else 0)
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
    # A malformed listing says nothing about which asks exist: compaction then drops nothing.
    listed = isinstance(listing, dict) and isinstance(listing.get('asks'), list)
    asks = [ask for ask in (listing['asks'] if listed else [])
            if isinstance(ask, dict) and isinstance(ask.get('id'), str)]
    # Only open asks take proposals; an answered ask keeps the founder's answer.
    known_ids = {ask['id'] for ask in asks if ask.get('status') == 'open'}
    count = import_proposals(tenants_dir, tenant, output, known_ids, source="task:" + args.task,
                             created=task.get('created'), current_ids={ask['id'] for ask in asks} if listed else None)
    print('Imported %d proposal(s)' % count)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
