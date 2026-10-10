#!/usr/bin/env python3
"""Read-only planner for importing tenant files from a source git ref into a destination ref.

Reads trees and blobs straight from git (no checkout, no writes), classifies every changed tenant file into a
sensitivity tier, compares it with the destination, and emits a plan. The plan holds counts and reasons only,
never the text that matched.

  T0 restricted: banking ids, credentials, contact/mailbox exports, extraction output. Never enters the shared
                 repo or a knowledge base.
  T1 internal:   tenant context, manifests, data notes. Imported, agent-readable under tenant isolation.
  T2 knowledge:  tenant wiki and research. Safe to embed once the T0 scan passes.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RESTRICTED_PATHS = (
    'tenants/*/documents/sold.md', 'tenants/*/data/extraction/out/**', 'tenants/*/data/extraction/campaign_pack/**/*.csv',
    'tenants/*/data/extraction/**/_archive/**/*.csv', '**/.env', '**/.env.*', '**/*.sqlite', '**/*.sqlite3', '**/*.pem', '**/*.key',
)
KNOWLEDGE_PATHS = ('tenants/*/wiki/**',)
SECRETS = re.compile(r'(?<![\w-])(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})(?![\w])'
                     r'|-----BEGIN [A-Z ]*PRIVATE KEY-----')
IBAN = re.compile(r'\b[A-Z]{2}\d{2}(?: ?[0-9A-Z]{4}){3,7}(?: ?[0-9A-Z]{1,4})?\b')
FRENCH_IBAN = re.compile(r'\bFR76[ 0-9]{18,}')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
CONTACT_EXPORT_EMAILS = 20
MAX_SCAN_BYTES = 8 * 1024 * 1024


def _regex(pattern):
    out, i = '', 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out, i = out + '(?:.*/)?', i + 3
        elif pattern.startswith('**', i):
            out, i = out + '.*', i + 2
        elif pattern[i] == '*':
            out, i = out + '[^/]*', i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile('^' + out + '$')


def matches(path, patterns):
    return any(_regex(p).match(path) for p in patterns)


def iban_valid(candidate):
    text = candidate.replace(' ', '')
    if not 15 <= len(text) <= 34:
        return False
    moved = text[4:] + text[:4]
    try:
        return int(''.join(str(int(c, 36)) for c in moved)) % 97 == 1
    except ValueError:
        return False


def content_reasons(data):
    if len(data) > MAX_SCAN_BYTES or b'\0' in data[:4096]:
        return [], 0
    text = data.decode('utf-8', 'replace')
    reasons = []
    if FRENCH_IBAN.search(text) or any(iban_valid(m.group(0)) for m in IBAN.finditer(text)):
        reasons.append('content:iban')
    if SECRETS.search(text):
        reasons.append('content:secret')
    emails = len(set(EMAIL.findall(text)))
    if emails >= CONTACT_EXPORT_EMAILS:
        reasons.append('content:contact-export')
    return reasons, emails


def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check, capture_output=True)


def tree(repo, ref):
    out = git(repo, 'ls-tree', '-r', '-z', '--full-tree', ref).stdout.decode('utf-8', 'replace')
    result = {}
    for row in filter(None, out.split('\0')):
        meta, path = row.split('\t', 1)
        result[path] = meta.split()[2]
    return result


def blobs(repo, shas):
    """Read many blobs through one git process."""
    shas = sorted(set(shas))
    if not shas:
        return {}
    proc = subprocess.run(['git', '-C', str(repo), 'cat-file', '--batch'], input=''.join(s + '\n' for s in shas).encode(), capture_output=True, check=True)
    data, pos, result = proc.stdout, 0, {}
    for sha in shas:
        end = data.index(b'\n', pos)
        header = data[pos:end].split()
        size = int(header[2]) if len(header) == 3 else 0
        result[sha] = data[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return result


def build_plan(repo, source, dest):
    repo = Path(repo)
    for ref in (source, dest):
        if git(repo, 'rev-parse', '--verify', '--quiet', ref + '^{commit}', check=False).returncode:
            raise ValueError('Unknown ref: ' + ref)
    base = git(repo, 'merge-base', source, dest).stdout.decode().strip()
    src_tree, dst_tree, base_tree = tree(repo, source), tree(repo, dest), tree(repo, base)
    changed = sorted(p for p in set(src_tree) | set(base_tree) if src_tree.get(p) != base_tree.get(p))
    contents = blobs(repo, [src_tree[p] for p in changed if p.startswith('tenants/') and p in src_tree])
    tenants, other, recommended = {}, [], {'include': [], 'hold': [], 'review': []}
    totals = {'T0': 0, 'T1': 0, 'T2': 0, 'files': 0, 'bytes': 0}
    for path in changed:
        if not path.startswith('tenants/') or path.count('/') < 2:
            other.append(path)
            continue
        slug = path.split('/')[1]
        deleted = path not in src_tree
        reasons = []
        if matches(path, RESTRICTED_PATHS):
            reasons.append('path:restricted')
        data = b'' if deleted else contents[src_tree[path]]
        found, emails = ([], 0) if deleted else content_reasons(data)
        reasons += found
        tier = 'T0' if reasons else ('T2' if matches(path, KNOWLEDGE_PATHS) else 'T1')
        if deleted:
            action = 'delete'
        elif path not in dst_tree:
            action = 'add'
        elif dst_tree[path] == src_tree[path]:
            action = 'same'
        elif dst_tree[path] == base_tree.get(path):
            action = 'modify'
        else:
            action = 'both-changed'
        entry = {'path': path, 'tier': tier, 'action': action, 'reasons': reasons, 'bytes': len(data)}
        if emails:
            entry['email_addresses'] = emails
        bucket = tenants.setdefault(slug, {'files': [], 'tiers': {'T0': 0, 'T1': 0, 'T2': 0}})
        bucket['files'].append(entry)
        bucket['tiers'][tier] += 1
        totals[tier] += 1
        totals['files'] += 1
        totals['bytes'] += len(data)
        if tier == 'T0':
            recommended['hold'].append(path)
        elif action in ('add', 'modify'):
            recommended['include'].append(path)
        elif action in ('both-changed', 'delete'):
            recommended['review'].append(path)
    trial = git(repo, 'merge-tree', '--write-tree', '--name-only', '--no-messages', dest, source, check=False)
    conflicts = [] if trial.returncode == 0 else [l for l in trial.stdout.decode().splitlines()[1:] if l]
    return {'source': source, 'dest': dest, 'base': base[:12], 'tenants': tenants, 'other_files': other,
            'merge': {'clean': trial.returncode == 0, 'conflicts': conflicts}, 'recommended': recommended, 'totals': totals}


def summary(plan):
    lines = ['%s -> %s (base %s): %d tenant files, %d other' % (plan['source'], plan['dest'], plan['base'], plan['totals']['files'], len(plan['other_files']))]
    for slug, info in sorted(plan['tenants'].items()):
        t = info['tiers']
        lines.append('  %-16s T0 %4d   T1 %4d   T2 %4d' % (slug, t['T0'], t['T1'], t['T2']))
    r, t = plan['recommended'], plan['totals']
    lines.append('totals: T0 %d (held), T1 %d, T2 %d | include %d, hold %d, review %d | merge %s' % (
        t['T0'], t['T1'], t['T2'], len(r['include']), len(r['hold']), len(r['review']),
        'clean' if plan['merge']['clean'] else 'CONFLICTS: ' + ', '.join(plan['merge']['conflicts'])))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repo', required=True, help='git repository holding both refs (the private ops checkout)')
    parser.add_argument('--source', required=True)
    parser.add_argument('--dest', default='origin/main')
    parser.add_argument('--out', help='write the full JSON plan here (mode 0600)')
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.repo, args.source, args.dest)
    except (ValueError, subprocess.CalledProcessError) as error:
        print('Cannot plan: %s' % error, file=sys.stderr)
        return 2
    if args.out:
        path = Path(args.out)
        path.write_text(json.dumps(plan, indent=1))
        path.chmod(0o600)
    print(summary(plan))
    return 0


if __name__ == '__main__':
    sys.exit(main())
