import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_worker_gc import clean_worktree, plan, remove


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


@pytest.mark.parametrize('kind', ['tracked', 'staged', 'untracked', 'ignored'])
@pytest.mark.parametrize('artifact', [True, False])
def test_changed_work_is_preserved_even_with_failed_cleanup(world, kind, artifact):
    repo, state, artifacts, tree = world
    (repo / 'review.md').write_text('accepted base\n')
    (repo / '.gitignore').write_text('private-cache/\n')
    subprocess.run(['git', '-C', str(repo), 'add', 'review.md', '.gitignore'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid',
                    'commit', '-q', '-m', 'base'], check=True)
    path = tree('t1', 'a1', artifact=artifact)
    file = path / ('private-cache/recovery.md' if kind == 'ignored' else
                   'later.md' if kind == 'untracked' else 'review.md')
    file.parent.mkdir(exist_ok=True)
    file.write_text('unarchived later work\n')
    if kind == 'staged':
        subprocess.run(['git', '-C', str(path), 'add', str(file)], check=True)
    assert not clean_worktree(path)
    assert verdicts(state, artifacts, include_failed=True, now=time.time() + 72 * 3600) == {'t1-a1': 'keep'}
    with pytest.raises(RuntimeError, match='preserve for recovery'):
        remove(path)
    assert file.read_text() == 'unarchived later work\n'
    assert str(path) in subprocess.run(['git', '-C', str(repo), 'worktree', 'list'], capture_output=True, text=True).stdout


def test_apply_rechecks_work_added_after_a_clean_plan(world):
    repo, state, artifacts, tree = world
    path = tree('t1', 'a1')
    assert verdicts(state, artifacts) == {'t1-a1': 'remove'}
    (path / 'later.md').write_text('keep this\n')
    with pytest.raises(RuntimeError, match='preserve for recovery'):
        remove(path)
    assert (path / 'later.md').read_text() == 'keep this\n'


@pytest.mark.parametrize('content', ['{}', '[]', 'null', 'not json', '{"attempt_id":"a1"}'])
def test_any_recovery_hold_protects_all_attempts(world, content):
    repo, state, artifacts, tree = world
    paths = [tree('t1', 'a1'), tree('t2', 'a2')]
    (state / 'recovery-required.json').write_text(content)
    assert verdicts(state, artifacts, include_failed=True) == {'t1-a1': 'keep', 't2-a2': 'keep'}
    for path in paths:
        with pytest.raises(RuntimeError, match='held, pending or active'):
            remove(path)
        assert path.exists()


@pytest.mark.parametrize('name', ['active.json', 'pending.json'])
@pytest.mark.parametrize('content', ['{}', '[]', 'null', '{"attempt_id":null}',
                                    '{"attempt_id":[]}', '{"attempt_id":""}'])
def test_malformed_assignment_state_fails_closed(world, name, content):
    repo, state, artifacts, tree = world
    tree('t1', 'a1')
    (state / name).write_text(content)
    assert verdicts(state, artifacts, include_failed=True) == {'t1-a1': 'keep'}


def test_apply_rechecks_a_hold_created_after_planning(world):
    repo, state, artifacts, tree = world
    path = tree('t1', 'a1')
    assert verdicts(state, artifacts) == {'t1-a1': 'remove'}
    (state / 'recovery-required.json').write_text('{}')
    with pytest.raises(RuntimeError, match='held, pending or active'):
        remove(path)
    assert path.exists()


def test_unknown_git_state_and_linked_targets_are_kept(world):
    repo, state, artifacts, tree = world
    unknown = state / 'worktrees' / 't1-a1'
    unknown.mkdir()
    (unknown / 'recovery.md').write_text('keep\n')
    linked = state / 'worktrees' / 't2-a2'
    linked.symlink_to(unknown, target_is_directory=True)
    assert verdicts(state, artifacts, min_age_hours=0, include_failed=True) == {'t1-a1': 'keep', 't2-a2': 'keep'}
    for path in (unknown, linked):
        with pytest.raises(RuntimeError, match='preserve for recovery'):
            remove(path)
    assert (unknown / 'recovery.md').read_text() == 'keep\n'


def test_normal_git_removal_preserves_a_locked_worktree(world):
    repo, state, artifacts, tree = world
    path = tree('t1', 'a1')
    subprocess.run(['git', '-C', str(repo), 'worktree', 'lock', str(path)], check=True)
    with pytest.raises(subprocess.CalledProcessError):
        remove(path)
    assert path.exists()


def test_detached_unretained_commit_is_preserved_until_history_is_saved(world):
    repo, state, artifacts, tree = world
    path = tree('t1', 'a1')
    (path / 'later.md').write_text('new committed work\n')
    subprocess.run(['git', '-C', str(path), 'add', 'later.md'], check=True)
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid',
                    'commit', '-q', '-m', 'later'], check=True)
    assert not subprocess.run(['git', '-C', str(path), 'status', '--porcelain'], capture_output=True).stdout
    assert verdicts(state, artifacts, now=time.time() + 72 * 3600) == {'t1-a1': 'keep'}
    with pytest.raises(RuntimeError, match='preserve for recovery'):
        remove(path)
    revision = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(['git', '-C', str(repo), 'branch', 'saved-recovery', revision], check=True)
    assert clean_worktree(path)
    remove(path)
    assert not path.exists()
    assert subprocess.run(['git', '-C', str(repo), 'show', 'saved-recovery:later.md'], check=True, capture_output=True, text=True).stdout == 'new committed work\n'
