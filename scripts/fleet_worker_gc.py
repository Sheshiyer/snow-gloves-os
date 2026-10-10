#!/usr/bin/env python3
"""Prune finished worker worktrees. Dry run unless --apply.

Removes an attempt's worktree only when its result artifact exists (the evidence is already kept) and the
attempt is not held, pending or active. A remote-artifact worker keeps no local result file; there the
coordinator-accepted success marker <state-root>/acknowledged/<task>-<attempt>.json counts instead. Changed worktrees, including ignored files, and revisions not
retained by a branch or tag are kept for recovery.
Failed, cancelled and interrupted attempts are kept for forensics unless --include-failed is given.
Worktrees younger than --min-age-hours are always kept. --include-failed never bypasses preservation.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def protected_attempts(state):
    names = set()
    for name in ('active.json', 'pending.json', 'recovery-required.json'):
        path = state / name
        if path.exists() or path.is_symlink():
            # The worker treats this file's presence as a global dispatch hold.
            # Its contents cannot narrow cleanup protection to one attempt.
            if name == 'recovery-required.json' or path.is_symlink() or not path.is_file():
                names.add('*')
                continue
            try:
                row = json.loads(path.read_text())
                attempt = row.get('attempt_id') if isinstance(row, dict) else None
                if not isinstance(attempt, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', attempt):
                    names.add('*')
                else:
                    names.add(attempt)
            except (OSError, ValueError, UnicodeError):
                names.add('*')  # unreadable worker state: protect everything
    names.update(p.stem[len('held-'):] for p in state.glob('held-*.json'))
    return names


def clean_worktree(tree):
    """Only a known checkout with no tracked, untracked or ignored work may go."""
    if tree.is_symlink() or not tree.is_dir():
        return False
    try:
        top = subprocess.run(['git', '-C', str(tree), 'rev-parse', '--show-toplevel'],
                             check=True, capture_output=True, text=True, timeout=30)
        if Path(top.stdout.strip()).resolve() != tree.resolve():
            return False
        retained = subprocess.run(['git', '-C', str(tree), 'for-each-ref', '--contains=HEAD',
                                   '--format=%(refname)', 'refs/heads', 'refs/remotes', 'refs/tags'],
                                  check=True, capture_output=True, timeout=30)
        if not retained.stdout.strip():
            return False
        status = subprocess.run(['git', '-C', str(tree), 'status', '--porcelain=v1',
                                 '--untracked-files=all', '--ignored=matching'],
                                check=True, capture_output=True, timeout=30)
        return not status.stdout
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        return False


def plan(state, artifacts, min_age_hours=24, include_failed=False, now=None):
    now = now or time.time()
    protected = protected_attempts(state)
    result = []
    for tree in sorted((state / 'worktrees').glob('*')) if (state / 'worktrees').is_dir() else []:
        task, _, attempt = tree.name.partition('-')
        age_hours = (now - tree.stat().st_mtime) / 3600
        has_artifact = ((artifacts / (tree.name + '.json')).is_file()
                        or (state / 'acknowledged' / (tree.name + '.json')).is_file())
        if '*' in protected or attempt in protected:
            verdict = 'keep: held, pending or active'
        elif age_hours < min_age_hours:
            verdict = 'keep: younger than %dh' % min_age_hours
        elif not has_artifact and not include_failed:
            verdict = 'keep: no result artifact (failed, cancelled or interrupted)'
        elif not clean_worktree(tree):
            verdict = 'keep: changed, unretained or unverified worktree; preserve for recovery'
        else:
            verdict = 'remove'
        result.append((tree, verdict))
    return result


def remove(tree, state=None):
    # Recheck because files can change after the plan was displayed. Normal
    # Git removal supplies its own final dirty/locked-worktree protection.
    protected = protected_attempts(state if state is not None else tree.parent.parent)
    if '*' in protected or tree.name.partition('-')[2] in protected:
        raise RuntimeError('held, pending or active worktree; preserve for recovery: %s' % tree)
    if not clean_worktree(tree):
        raise RuntimeError('changed, unretained or unverified worktree; preserve for recovery: %s' % tree)
    common = subprocess.run(['git', '-C', str(tree), 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True, timeout=30)
    if common.returncode:
        raise RuntimeError('not a git worktree: %s' % tree)
    repo = Path(common.stdout.strip()).parent
    subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', str(tree)], check=True, capture_output=True, timeout=60)
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
            remove(tree, state=state)
            removed += 1
    print('removed %d' % removed if args.apply else 'dry run: nothing removed (use --apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
