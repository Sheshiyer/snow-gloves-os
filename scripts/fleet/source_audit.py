#!/usr/bin/env python3
"""Read-only tenant-reference and byte-bound private-transfer audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

sys.dont_write_bytecode = True
import yaml

MAX_BYTES = 2_000_000


def read_bytes(path, limit=MAX_BYTES):
    if path.is_symlink():
        raise ValueError('symlink input held')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('unbounded or nonregular input held')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if len(raw) > limit or identity(before) != identity(after):
        raise ValueError('changed input held')
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('invalid relative path')
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('invalid relative path')
    return value


def unique(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('duplicate input key')
        out[key] = value
    return out


class ClosedLoader(yaml.SafeLoader):
    pass


def mapping(loader, node):
    return unique(loader.construct_pairs(node, deep=True))


ClosedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def tenant_audit(root):
    rows, failures = [], []
    manifests = sorted((root / 'tenants').glob('*/sources.yaml'))
    if not manifests:
        raise ValueError('no tenant source manifests')
    for manifest in manifests:
        slug = manifest.parent.name
        if not re.fullmatch('[a-z][a-z0-9-]{0,62}', slug):
            raise ValueError('invalid tenant slug')
        tenant = manifest.parent.resolve()
        if manifest.parent.is_symlink() or not tenant.is_relative_to(root / 'tenants'):
            raise ValueError('tenant path outside root')
        raw = read_bytes(manifest)
        value = yaml.load(raw, Loader=ClosedLoader)
        if not isinstance(value, dict) or set(value) != {'tenant', 'sources'} or value['tenant'] != slug:
            raise ValueError('tenant manifest scope mismatch')
        if not isinstance(value['sources'], list) or len(value['sources']) > 100:
            raise ValueError('invalid source list')
        ids = set()
        for source in value['sources']:
            if not isinstance(source, dict) or not isinstance(source.get('id'), str) or source['id'] in ids:
                raise ValueError('invalid or duplicate source identity')
            ids.add(source['id'])
            if (source.get('type') != 'filesystem' or type(source.get('ingest')) is not bool
                    or set(source) - {'id', 'type', 'path', 'ingest', 'include_glob', 'exclude_glob', 'max_file_bytes', 'note'}):
                raise ValueError('unsupported source contract')
            row = {'tenant': slug, 'source_id': source['id'], 'manifest_sha256': digest(raw),
                   'path': source.get('path'), 'files': []}
            path = source.get('path')
            if not isinstance(path, str) or not path:
                raise ValueError('invalid source path')
            if source.get('ingest') is False:
                row.update(status='held', reason='Explicitly excluded from tenant ingestion; capability presence grants no authority',
                           present=Path(path).expanduser().exists())
                rows.append(row)
                continue
            try:
                relative(path)
                target = root / path
                resolved = target.resolve()
                if not resolved.is_relative_to(tenant) or target.is_symlink():
                    raise ValueError('cross-tenant or symlink source')
                if not target.exists():
                    raise ValueError('missing source')
                includes = source.get('include_glob', ['**/*.md'])
                excludes = source.get('exclude_glob', [])
                limit = source.get('max_file_bytes', 500000)
                if (not isinstance(includes, list) or not includes or not isinstance(excludes, list)
                        or any(not isinstance(x, str) for x in includes + excludes)
                        or type(limit) is not int or not 0 < limit <= MAX_BYTES):
                    raise ValueError('invalid ingest filters')
                candidates = sorted(target.rglob('*')) if target.is_dir() else [target]
                for candidate in candidates:
                    if candidate.is_symlink():
                        raise ValueError('symlink member held')
                    if not candidate.is_file():
                        continue
                    name = candidate.relative_to(target) if target.is_dir() else Path(candidate.name)
                    if any(part.startswith('.') for part in name.parts):
                        continue
                    matches = lambda pattern: name.match(pattern) or (pattern.startswith('**/') and name.match(pattern[3:]))
                    if not any(matches(p) for p in includes) or any(matches(p) for p in excludes):
                        continue
                    data = read_bytes(candidate, limit)
                    row['files'].append({'path': str(candidate.relative_to(root)), 'bytes': len(data), 'sha256': digest(data)})
                row.update(status='resolved', reason='Current tenant-local paths and bounded regular bytes verified')
            except (ValueError, OSError):
                row.update(status='held', reason='Missing, unsafe, changed or unsupported source; reconciliation required', files=[])
                failures.append({'tenant': slug, 'source_id': source['id']})
            rows.append(row)
    return {'sources': rows, 'unexpected_holds': failures, 'tenants': len(manifests)}


def disposition_audit(root, policy_path, expected_digest, candidates=None):
    raw = read_bytes(policy_path)
    if not isinstance(expected_digest, str) or digest(raw) != expected_digest:
        raise ValueError('policy checksum mismatch')
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict) or value.get('schema') != 'snowgloves.controller-data-policy.v1':
        raise ValueError('invalid exclusion policy')
    excluded = value.get('excluded_paths')
    records = value.get('dispositions')
    if not isinstance(excluded, list) or not excluded or not isinstance(records, list):
        raise ValueError('missing dispositions')
    excluded = [relative(p) for p in excluded]
    if (any(not isinstance(r, dict) for r in records) or len(set(excluded)) != len(excluded)
            or {r.get('path') for r in records} != set(excluded) or len(records) != len(excluded)):
        raise ValueError('dispositions must cover exactly the excluded paths')
    result = []
    for record in records:
        if (record.get('disposition') != 'held-private' or record.get('transfer') is not False
                or record.get('ingest') is not False or not isinstance(record.get('reason'), str)
                or not record['reason'].strip()):
            raise ValueError('invalid private hold')
        path = root / relative(record['path'])
        if not path.resolve().is_relative_to(root):
            raise ValueError('disposition outside root')
        if digest(read_bytes(path)) != record.get('sha256'):
            raise ValueError('held file bytes changed; disposition must be renewed')
        result.append({'path': record['path'], 'sha256': record['sha256'], 'disposition': 'held-private',
                       'transfer': False, 'ingest': False})
    rejected = []
    if candidates is not None:
        if not isinstance(candidates, list):
            raise ValueError('candidate list must be relative paths')
        held_digests = {r['sha256'] for r in result}
        for name in candidates:
            name = relative(name)
            candidate = root / name
            if (name in excluded or candidate.is_symlink()
                    or not candidate.resolve().is_relative_to(root)):
                rejected.append(name)
            elif digest(read_bytes(candidate)) in held_digests:
                rejected.append(name)  # Renaming, hardlinking or copying cannot clear a byte-bound hold.
        rejected = sorted(set(rejected))
    return {'policy_sha256': digest(raw), 'files': result, 'rejected_candidates': rejected,
            'transfer_allowed': not rejected, 'scope': 'These exclusions only; passing is not a general secret-scan or transfer authorization'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--policy')
    parser.add_argument('--policy-digest')
    parser.add_argument('--candidate-list')
    args = parser.parse_args(argv)
    try:
        root = Path(args.data_root)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError('data root must be an existing absolute directory')
        root = root.resolve()
        result = {'schema': 'snowgloves.controller-source-audit.v1', 'root': str(root), 'tenant_audit': tenant_audit(root)}
        if args.policy:
            candidates = json.loads(read_bytes(Path(args.candidate_list)), object_pairs_hook=unique) if args.candidate_list else None
            result['dispositions'] = disposition_audit(root, Path(args.policy), args.policy_digest, candidates)
        elif args.policy_digest or args.candidate_list:
            raise ValueError('policy is required')
        result['passed'] = not result['tenant_audit']['unexpected_holds'] and not result.get('dispositions', {}).get('rejected_candidates')
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 2
    except (ValueError, OSError, TypeError, yaml.YAMLError, RuntimeError):
        print(json.dumps({'schema': 'snowgloves.controller-source-audit.v1', 'passed': False,
                          'error': 'Invalid, changed or unsafe inputs; no files modified'}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
