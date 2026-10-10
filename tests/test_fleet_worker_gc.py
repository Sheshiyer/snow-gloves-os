import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_worker_gc import plan, remove


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'i'], check=True)
    state, artifacts = tmp_path / 'state', tmp_path / 'artifacts'
    (state / 'worktrees').mkdir(parents=True)
    artifacts.mkdir()

    def tree(task, attempt, age_hours=48, artifact=True):
        path = state / 'worktrees' / ('%s-%s' % (task, attempt))
        subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-q', '--detach', str(path), 'HEAD'], check=True)
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))
        if artifact:
            (artifacts / (path.name + '.json')).write_text('{}')
        return path
    return repo, state, artifacts, tree


def verdicts(state, artifacts, **kw):
    return {t.name: v.split(':')[0] for t, v in plan(state, artifacts, **kw)}


def test_only_old_worktrees_with_an_artifact_are_removed(world):
    repo, state, artifacts, tree = world
    tree('t1', 'a1')
    tree('t2', 'a2', age_hours=1)
    tree('t3', 'a3', artifact=False)
    assert verdicts(state, artifacts) == {'t1-a1': 'remove', 't2-a2': 'keep', 't3-a3': 'keep'}


def test_failed_attempts_go_only_with_the_explicit_flag(world):
    repo, state, artifacts, tree = world
    tree('t3', 'a3', artifact=False)
    assert verdicts(state, artifacts, include_failed=True) == {'t3-a3': 'remove'}


@pytest.mark.parametrize('name', ['active.json', 'pending.json', 'recovery-required.json'])
def test_attempts_the_worker_still_holds_are_never_removed(world, name):
    repo, state, artifacts, tree = world
    tree('t1', 'a1')
    (state / name).write_text(json.dumps({'attempt_id': 'a1'}))
    assert verdicts(state, artifacts, include_failed=True) == {'t1-a1': 'keep'}


def test_held_attempt_files_protect_their_worktree(world):
    repo, state, artifacts, tree = world
    tree('t1', 'a1')
    (state / 'held-a1.json').write_text('{}')
    assert verdicts(state, artifacts) == {'t1-a1': 'keep'}


def test_unreadable_worker_state_protects_everything(world):
    repo, state, artifacts, tree = world
    tree('t1', 'a1')
    (state / 'active.json').write_text('not json')
    assert verdicts(state, artifacts, include_failed=True) == {'t1-a1': 'keep'}


def test_remove_deletes_the_worktree_and_its_git_registration(world):
    repo, state, artifacts, tree = world
    path = tree('t1', 'a1')
    remove(path)
    assert not path.exists()
    assert str(path) not in subprocess.run(['git', '-C', str(repo), 'worktree', 'list'], capture_output=True, text=True).stdout
