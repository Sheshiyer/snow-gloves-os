#!/usr/bin/env python3
"""Prune finished worker worktrees. Dry run unless --apply.

Removes an attempt's worktree only when its result artifact exists (the evidence is already kept) and the
attempt is not held, pending or active. Failed, cancelled and interrupted attempts are kept for forensics
unless --include-failed is given. Worktrees younger than --min-age-hours are always kept.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def protected_attempts(state):
    names = set()
    for name in ('active.json', 'pending.json', 'recovery-required.json'):
        path = state / name
        if path.is_file():
            try:
                row = json.loads(path.read_text())
                names.add(row.get('attempt_id', ''))
            except ValueError:
                names.add('*')  # unreadable worker state: protect everything
    names.update(p.stem[len('held-'):] for p in state.glob('held-*.json'))
    return names


def plan(state, artifacts, min_age_hours=24, include_failed=False, now=None):
    now = now or time.time()
    protected = protected_attempts(state)
    result = []
    for tree in sorted((state / 'worktrees').glob('*')) if (state / 'worktrees').is_dir() else []:
        task, _, attempt = tree.name.partition('-')
        age_hours = (now - tree.stat().st_mtime) / 3600
        has_artifact = (artifacts / (tree.name + '.json')).is_file()
        if '*' in protected or attempt in protected:
            verdict = 'keep: held, pending or active'
        elif age_hours < min_age_hours:
            verdict = 'keep: younger than %dh' % min_age_hours
        elif not has_artifact and not include_failed:
            verdict = 'keep: no result artifact (failed, cancelled or interrupted)'
        else:
            verdict = 'remove'
        result.append((tree, verdict))
    return result


def remove(tree):
    common = subprocess.run(['git', '-C', str(tree), 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True, timeout=30)
    if common.returncode:
        raise RuntimeError('not a git worktree: %s' % tree)
    repo = Path(common.stdout.strip()).parent
    subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', '--force', str(tree)], check=True, capture_output=True, timeout=60)
    subprocess.run(['git', '-C', str(repo), 'worktree', 'prune'], check=True, capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--state-root', required=True)
    parser.add_argument('--artifacts-root', required=True)
    parser.add_argument('--min-age-hours', type=float, default=24)
    parser.add_argument('--include-failed', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    state, artifacts = Path(args.state_root).resolve(), Path(args.artifacts_root).resolve()
    removed = 0
    for tree, verdict in plan(state, artifacts, args.min_age_hours, args.include_failed):
        print('%-8s %s  (%s)' % ('REMOVE' if verdict == 'remove' and args.apply else verdict.split(':')[0], tree.name, verdict))
        if verdict == 'remove' and args.apply:
            remove(tree)
            removed += 1
    print('removed %d' % removed if args.apply else 'dry run: nothing removed (use --apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
