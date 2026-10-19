"""Tests for tenant admission, kickoff briefs and proposal import."""
import json
import os
import tempfile
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fleet_kickoff
from fleet_admit_tenants import admit, _write_config
from fleet_kickoff import kickoff_brief, _task_body
from fleet_asks_import import import_proposals, _last_json_array


def _git_init(path):
    """A real, empty Git repository: admission enumerates its object database."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(['git', 'init', '-q', str(path)], check=True)


def _git_commit_all(path, message='snapshot'):
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
    subprocess.run(['git', '-C', str(path), 'add', '-A'], check=True, env=env)
    subprocess.run(['git', '-C', str(path), 'commit', '-q', '-m', message], check=True, env=env)


GIT_ROOT = tempfile.mkdtemp(prefix='admit-root-')
_git_init(GIT_ROOT)


def _base_config():
    return {
        'data_root': '/tmp/ops',
        'projects': {
            'snowgloves': {
                'root': '/tmp/repo',
                'tenant': 'heyzack',
                'organization': 'heyzack',
                'runtimes': ['codex'],
            }
        },
        'principals': {
            'founder': {'token': 'founder-secret-token-x', 'projects': ['snowgloves']},
        },
        'workers': {
            'mac-coding-1': {'token': 'worker-secret-token-x', 'projects': ['snowgloves'], 'runtimes': ['codex']},
        },
        'capacity': 1,
        'lease_seconds': 30,
        'allowed_origins': [],
    }


# ---------------------------------------------------------------------------
# admit
# ---------------------------------------------------------------------------

def test_admit_keeps_existing_project_mapped_to_tenant():
    config = _base_config()
    result = admit(config, ['heyzack', 'tryambakam'], 'new-org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    assert 'heyzack' not in result['projects']
    assert result['projects']['snowgloves']['tenant'] == 'heyzack'
    assert result['projects']['tryambakam'] == {
        'tenant': 'tryambakam', 'organization': 'new-org', 'runtimes': ['codex'], 'root': GIT_ROOT,
        'tenant_isolated': True}


def test_admit_appends_to_principal_and_workers():
    config = _base_config()
    result = admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    assert 'tryambakam' in result['principals']['founder']['projects']
    assert 'tryambakam' in result['workers']['mac-coding-1']['projects']


def test_admit_never_adds_write_grants():
    config = _base_config()
    result = admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    project = result['projects']['tryambakam']
    assert 'write' not in project
    assert 'fanout' not in project
    assert 'write_projects' not in result['principals']['founder']


def test_admit_is_idempotent():
    config = _base_config()
    result = admit(config, ['heyzack', 'tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    result2 = admit(result, ['heyzack', 'tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    assert result2 == result


def test_admit_does_not_mutate_input():
    config = _base_config()
    admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    assert 'tryambakam' not in config['projects']
    assert config['principals']['founder']['projects'] == ['snowgloves']


# ---------------------------------------------------------------------------
# kickoff_brief
# ---------------------------------------------------------------------------

def _fact_ask(i, status='open'):
    return {'id': 'a%032d' % i, 'tenant': 'heyzack', 'kind': 'fact', 'role': 'librarian',
            'title': 'Ask %d' % i, 'source': 'context/offer.md', 'answer_type': 'text',
            'proposed': None, 'status': status}


def test_kickoff_brief_caps_at_40_and_16000():
    asks = [_fact_ask(i) for i in range(50)]
    brief = kickoff_brief('heyzack', asks)
    assert len(brief) <= 16000
    assert ('a%032d' % 39) in brief
    assert ('a%032d' % 40) not in brief


def test_kickoff_brief_truncates_long_content():
    asks = [_fact_ask(i) for i in range(50)]
    for ask in asks:
        ask['title'] = 'T' * 200
        ask['source'] = 'S' * 200
    brief = kickoff_brief('heyzack', asks)
    assert len(brief) <= 16000


def test_kickoff_brief_filters_non_fact_and_answered():
    asks = [
        {'id': 'a' * 32, 'tenant': 'heyzack', 'kind': 'fact', 'role': 'librarian',
         'title': 'Open fact', 'source': 'context/offer.md', 'answer_type': 'text',
         'proposed': None, 'status': 'open'},
        {'id': 'b' * 32, 'tenant': 'heyzack', 'kind': 'decision', 'role': 'chief-of-staff',
         'title': 'Decision', 'source': 'proposal', 'answer_type': 'yes_no',
         'proposed': None, 'status': 'open'},
        {'id': 'c' * 32, 'tenant': 'heyzack', 'kind': 'fact', 'role': 'librarian',
         'title': 'Answered', 'source': 'context/other.md', 'answer_type': 'text',
         'proposed': None, 'status': 'answered'},
    ]
    brief = kickoff_brief('heyzack', asks)
    assert ('a' * 32) in brief
    assert ('b' * 32) not in brief
    assert ('c' * 32) not in brief


# ---------------------------------------------------------------------------
# import_proposals
# ---------------------------------------------------------------------------

def test_import_proposals_filters_and_writes(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    known = {'id1', 'id2'}
    artifact = ('Here are proposals.\n'
                '[{"ask_id":"id1","proposed":"EUR 99","evidence":"ctx"},'
                '{"ask_id":"id2","proposed":"my secret token","evidence":"x"},'
                '{"ask_id":"unknown","proposed":"value","evidence":"x"}]')
    count = import_proposals(tenants_dir, 'heyzack', artifact, known)
    assert count == 1
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    assert len(lines) == count
    entry = json.loads(lines[0])
    assert entry['ask_id'] == 'id1'
    assert entry['proposed'] == 'EUR 99'


def test_import_proposals_ignores_sensitive_and_oversized(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = json.dumps([
        {'ask_id': 'id1', 'proposed': 'my api key is abc', 'evidence': 'x'},
        {'ask_id': 'id2', 'proposed': 'x' * 501, 'evidence': 'x'},
        {'ask_id': 'id3', 'proposed': 'safe value', 'evidence': 'x'},
    ])
    count = import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2', 'id3'})
    assert count == 1
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    assert len(lines) == count
    assert json.loads(lines[0])['ask_id'] == 'id3'


def test_import_proposals_malformed_json(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    assert import_proposals(tenants_dir, 'heyzack', 'no json here', {'id1'}) == 0
    assert not (tenants_dir / 'heyzack' / 'asks').exists()


def test_import_proposals_takes_last_array(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = '[{"ask_id":"id1","proposed":"old"}]\nText\n[{"ask_id":"id1","proposed":"new"}]'
    count = import_proposals(tenants_dir, 'heyzack', artifact, {'id1'})
    assert count == 1
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    assert json.loads(lines[0])['proposed'] == 'new'


def test_import_proposals_count_matches_lines(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = json.dumps([
        {'ask_id': 'a', 'proposed': 'one', 'evidence': 'x'},
        {'ask_id': 'b', 'proposed': 'two', 'evidence': 'x'},
        {'ask_id': 'c', 'proposed': 'three', 'evidence': 'x'},
    ])
    count = import_proposals(tenants_dir, 'heyzack', artifact, {'a', 'b', 'c'})
    assert count == 3
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    assert len(lines) == count


# ---------------------------------------------------------------------------
# atomic config write (fleet_admit_tenants --write)
# ---------------------------------------------------------------------------

def test_write_config_is_atomic_mode_0600(tmp_path):
    config_path = tmp_path / 'coordinator.json'
    config_path.write_text(json.dumps(_base_config()))
    result = admit(_base_config(), ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    _write_config(config_path, result)
    mode = stat.S_IMODE(config_path.stat().st_mode)
    assert mode == 0o600
    loaded = json.loads(config_path.read_text())
    assert 'tryambakam' in loaded['projects']


# ---------------------------------------------------------------------------
# bounded last-json-array search (fleet_asks_import)
# ---------------------------------------------------------------------------

def test_last_json_array_finds_final_array_in_large_artifact():
    final = '[{"ask_id":"id1","proposed":"final"}]'
    chunk = '[' + 'a' * 80 + '\n'
    target = 256 * 1024
    repeats = (target - len(final)) // len(chunk) + 1
    text = chunk * repeats + final
    assert len(text) >= 256 * 1024
    assert text.count('[') > 1000
    result = _last_json_array(text)
    assert result is not None
    assert result[0]['proposed'] == 'final'


def test_last_json_array_bounded_when_no_valid_array():
    chunk = '[' + 'a' * 50 + '\n'
    text = chunk * 300
    assert text.count('[') > 200
    assert _last_json_array(text) is None


# ---------------------------------------------------------------------------
# evidence sensitive filter + cap (fleet_asks_import)
# ---------------------------------------------------------------------------

def test_import_proposals_drops_sensitive_evidence(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = json.dumps([
        {'ask_id': 'id1', 'proposed': 'safe', 'evidence': 'my api key is abc'},
        {'ask_id': 'id2', 'proposed': 'safe2', 'evidence': 'clean evidence'},
    ])
    count = import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2'})
    assert count == 1
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    entry = json.loads(lines[0])
    assert entry['ask_id'] == 'id2'
    assert entry['evidence'] == 'clean evidence'


def test_import_proposals_caps_evidence_at_500(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = json.dumps([
        {'ask_id': 'id1', 'proposed': 'safe', 'evidence': 'e' * 600},
    ])
    count = import_proposals(tenants_dir, 'heyzack', artifact, {'id1'})
    assert count == 1
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    entry = json.loads(lines[0])
    assert len(entry['evidence']) == 500


# ---------------------------------------------------------------------------
# wave flag and idempotency key (fleet_kickoff)
# ---------------------------------------------------------------------------

def test_task_body_idempotency_key_uses_wave():
    body = _task_body('heyzack', 'heyzack', 'brief', '2026-10-16')
    assert body['idempotency_key'] == 'kickoff-heyzack-2026-10-16'
    body2 = _task_body('heyzack', 'heyzack', 'brief', '2027-01-01')
    assert body2['idempotency_key'] == 'kickoff-heyzack-2027-01-01'
    assert body['access'] == 'read'
    assert body['category'] == 'development'


def test_kickoff_brief_truncates_at_line_boundary():
    asks = [_fact_ask(i) for i in range(50)]
    for ask in asks:
        ask['title'] = 'T' * 200
        ask['source'] = 'S' * 200
    brief = kickoff_brief('heyzack', asks)
    assert len(brief) <= 16000
    assert 'Return a JSON array' in brief and brief.rstrip().endswith('500 characters or fewer.')
    ask_lines = [line for line in brief.splitlines() if line.startswith('- ')]
    assert 0 < len(ask_lines) < 40
    assert all(line.endswith(')') for line in ask_lines)


# ---------------------------------------------------------------------------
# CLI failure handling (fleet_kickoff)
# ---------------------------------------------------------------------------

def _fact_asks_for_main():
    return [{'id': 'a' * 32, 'tenant': 'heyzack', 'kind': 'fact', 'role': 'librarian',
             'title': 'q', 'source': 'context/x.md', 'answer_type': 'text',
             'proposed': None, 'status': 'open'}]


def test_kickoff_main_warns_and_keeps_going(monkeypatch, capsys, tmp_path):
    token_file = tmp_path / 'token'
    token_file.write_text('secret-token-value')
    calls = []

    def fake_list(coordinator, token, project):
        calls.append(project)
        return None if project == 'bad' else _fact_asks_for_main()

    monkeypatch.setattr(fleet_kickoff, '_list_asks', fake_list)
    monkeypatch.setattr(sys, 'argv', ['fleet_kickoff.py', '--coordinator', 'http://x',
                                      '--token-file', str(token_file),
                                      '--projects', 'bad,good'])
    rc = fleet_kickoff.main()
    assert rc == 1
    assert calls == ['bad', 'good']
    err = capsys.readouterr().err
    assert 'bad' in err
    assert 'secret-token-value' not in err


def test_kickoff_submit_failure_warns_per_project(monkeypatch, capsys, tmp_path):
    token_file = tmp_path / 'token'
    token_file.write_text('secret-token-value')
    submitted = []

    def fake_submit(coordinator, token, project, tenant, brief, wave):
        submitted.append(project)
        return 'kickoff failed: HTTP 500'

    monkeypatch.setattr(fleet_kickoff, '_list_asks', lambda c, t, p: _fact_asks_for_main())
    monkeypatch.setattr(fleet_kickoff, '_submit_task', fake_submit)
    monkeypatch.setattr(sys, 'argv', ['fleet_kickoff.py', '--coordinator', 'http://x',
                                      '--token-file', str(token_file), '--projects', 'p1,p2',
                                      '--submit'])
    rc = fleet_kickoff.main()
    assert rc == 1
    assert submitted == ['p1', 'p2']
    err = capsys.readouterr().err
    assert 'p1' in err and 'p2' in err
    assert 'secret-token-value' not in err


def test_admit_requires_root_for_local_workers():
    config = _base_config()
    with pytest.raises(ValueError, match='root'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'])
    with pytest.raises(ValueError, match='root'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root='relative/repo')


def test_admit_remote_only_workers_need_no_root():
    config = _base_config()
    config['workers']['mac-creative'] = {'token': 'creative-secret-token-x', 'projects': [], 'runtimes': ['codex'], 'remote_artifacts': True}
    with pytest.raises(ValueError, match='project_roots'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-creative'])
    result = admit(config, ['tryambakam'], 'org', 'founder', ['mac-creative'], remote_roots_staged=True)
    assert 'root' not in result['projects']['tryambakam']
    assert 'tryambakam' in result['workers']['mac-creative']['projects']


def test_task_body_uses_development_category_without_business_context():
    body = _task_body('tryambakam', 'tryambakam', 'brief', '2026-10-16')
    assert body.get('category', 'development') == 'development'
    assert 'business_context' not in body
    assert body['access'] == 'read'


def test_import_proposals_rejects_empty_proposed(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = '[{"ask_id":"id1","proposed":"","evidence":"ctx"},{"ask_id":"id2","proposed":"   ","evidence":"ctx"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2'}) == 0
    assert not (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').exists()


def test_kickoff_task_body_is_accepted_by_the_coordinator(tmp_path):
    from test_fleet_coordinator import fleet as _fleet  # noqa: F401
    import subprocess
    from lib.fleet_coordinator import Coordinator
    repo = tmp_path / 'repo'; repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    config = {'data_root': str(tmp_path / 'ops'),
              'projects': {'snowgloves': {'root': str(repo), 'tenant': 'heyzack', 'organization': 'heyzack', 'runtimes': ['codex']}},
              'principals': {'founder': {'token': 'founder-secret-token-x', 'projects': ['snowgloves']}},
              'workers': {}, 'capacity': 1, 'lease_seconds': 30, 'allowed_origins': []}
    c = Coordinator(config, clock=lambda: 100.0)
    try:
        task = c.submit('founder', config['principals']['founder'], _task_body('snowgloves', 'heyzack', 'Propose values.', '2026-10-16'))
        assert task['status'] == 'queued' and task['category'] == 'development'
    finally:
        c.close()


def test_admit_rejects_unknown_principal_or_worker():
    config = _base_config()
    with pytest.raises(ValueError, match='principal'):
        admit(config, ['tryambakam'], 'org', 'foundr', ['mac-coding-1'], root=GIT_ROOT)
    with pytest.raises(ValueError, match='worker'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-codng-1'], root=GIT_ROOT)
    with pytest.raises(ValueError, match='worker'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-codng-1'])


def test_kickoff_skips_projects_without_open_fact_asks(monkeypatch, capsys, tmp_path):
    token_file = tmp_path / 'token'
    token_file.write_text('secret-token-value')
    submitted = []
    only_other = [dict(_fact_asks_for_main()[0], kind='connect', role='dispatcher'),
                  dict(_fact_asks_for_main()[0], id='b' * 32, status='answered')]
    monkeypatch.setattr(fleet_kickoff, '_list_asks', lambda c, t, p: only_other if p == 'quiet' else _fact_asks_for_main())
    monkeypatch.setattr(fleet_kickoff, '_submit_task', lambda c, t, project, *a: submitted.append(project))
    monkeypatch.setattr(sys, 'argv', ['fleet_kickoff.py', '--coordinator', 'http://x', '--token-file', str(token_file),
                                      '--projects', 'quiet,busy', '--submit'])
    assert fleet_kickoff.main() == 0
    assert submitted == ['busy']


def test_admit_requires_existing_git_checkout_root(tmp_path):
    config = _base_config()
    with pytest.raises(ValueError, match='Git'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=str(tmp_path / 'missing'))
    plain = tmp_path / 'plain'; plain.mkdir()
    with pytest.raises(ValueError, match='Git'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=str(plain))


def test_admit_rejects_unroutable_project_ids():
    config = _base_config()
    with pytest.raises(ValueError, match='project id'):
        admit(config, ['_demo'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)


def test_import_proposals_rejects_control_characters(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = '[{"ask_id":"id1","proposed":"line one\\nline two","evidence":"ctx"},{"ask_id":"id2","proposed":"EUR 99","evidence":"ctx"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2'}) == 1
    lines = (tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()
    assert [json.loads(line)['ask_id'] for line in lines] == ['id2']


def test_admit_rejects_blank_organization():
    config = _base_config()
    for organization in ('', '   ', None):
        with pytest.raises(ValueError, match='organization'):
            admit(config, ['tryambakam'], organization, 'founder', ['mac-coding-1'], root=GIT_ROOT)


def test_import_skips_proposals_already_recorded(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = '[{"ask_id":"id1","proposed":"EUR 99","evidence":"ctx"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}) == 1
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}) == 0
    assert len((tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()) == 1


def test_import_ignores_bracketed_text_inside_proposals(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = 'Done.\n[{"ask_id":"id1","proposed":"EUR 99","evidence":"price list, source [1]"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}) == 1


def test_admit_rejects_project_id_mapped_to_another_tenant():
    config = _base_config()
    config['projects']['tryambakam'] = dict(config['projects']['snowgloves'], tenant='other-tenant')
    with pytest.raises(ValueError, match='tryambakam'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)


def test_admit_requires_at_least_one_worker():
    config = _base_config()
    with pytest.raises(ValueError, match='worker'):
        admit(config, ['tryambakam'], 'org', 'founder', [])


def test_import_survives_hundreds_of_citation_brackets(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    evidence = '[1]' * 160
    entries = [{'ask_id': 'id%d' % i, 'proposed': 'v%d' % i, 'evidence': evidence} for i in range(3)]
    artifact = 'Summary.\n' + json.dumps(entries)
    assert artifact.count('[') > 400
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id0', 'id1', 'id2'}) == 3


def test_admit_requires_a_worker_that_can_claim_read_only_codex_tasks():
    config = _base_config()
    config['workers']['mac-coding-1']['runtimes'] = ['claude']
    with pytest.raises(ValueError, match='read-only codex'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    config = _base_config()
    config['workers']['mac-coding-1']['access_modes'] = ['write']
    with pytest.raises(ValueError, match='read-only codex'):
        admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)


def test_import_ignores_nested_arrays_and_bracket_text_before_the_array(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    prose = 'Notes: ' + '[{ not json ' * 300 + '\n'
    entries = [{'ask_id': 'id1', 'proposed': 'EUR 99', 'evidence': 'see refs', 'citations': [{'ask_id': 'ref'}]}]
    assert import_proposals(tenants_dir, 'heyzack', prose + json.dumps(entries), {'id1'}) == 1
    record = json.loads((tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl').read_text().splitlines()[0])
    assert record['ask_id'] == 'id1'


def test_kickoff_body_with_emoji_titles_fits_the_coordinator_limit():
    from fleet_kickoff import _encode_body
    asks = [dict(_fact_ask(i), title='\U0001F600' * 160, source='context/offer.md') for i in range(40)]
    body = _encode_body(_task_body('heyzack', 'heyzack', kickoff_brief('heyzack', asks), '2026-10-16'))
    assert len(body) <= 64 * 1024
    assert json.loads(body.decode('utf-8'))['brief'].count('\U0001F600') > 1000


def test_import_rejects_lone_surrogates(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = '[{"ask_id":"id1","proposed":"bad \\ud800","evidence":"x"},{"ask_id":"id2","proposed":"EUR 99","evidence":"x"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2'}) == 1


def test_admit_refuses_a_shared_root_for_several_tenants(tmp_path):
    config = _base_config()
    with pytest.raises(ValueError, match='tenant'):
        admit(config, ['tenant-a', 'tenant-b'], 'org', 'founder', ['mac-coding-1'], root=GIT_ROOT)
    for name in ('tenant-a', 'tenant-b'):
        _git_init(tmp_path / name)
    result = admit(config, ['tenant-a', 'tenant-b'], 'org', 'founder', ['mac-coding-1'], root=str(tmp_path / '{tenant}'))
    assert result['projects']['tenant-a']['root'] == str(tmp_path / 'tenant-a')
    assert result['projects']['tenant-b']['root'] == str(tmp_path / 'tenant-b')


def test_admit_refuses_a_root_holding_other_tenants(tmp_path):
    config = _base_config()
    shared = tmp_path / 'ops'
    _git_init(shared)
    os.makedirs(shared / 'tenants' / 'tenant-a')
    os.makedirs(shared / 'tenants' / 'other-tenant')
    with pytest.raises(ValueError, match='other tenants'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(shared))


def test_reimporting_the_same_task_is_a_no_op_beyond_the_tail(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    asks_dir = tenants_dir / 'heyzack' / 'asks'
    asks_dir.mkdir(parents=True)
    old = '[{"ask_id":"id1","proposed":"EUR 99","evidence":"x"}]'
    assert import_proposals(tenants_dir, 'heyzack', old, {'id1'}, source='task-old') == 1
    filler = json.dumps({'ask_id': 'f' * 32, 'proposed': 'x' * 400}) + '\n'
    with (asks_dir / 'proposed.jsonl').open('a') as stream:
        stream.write(filler * 1000)
    new = '[{"ask_id":"id1","proposed":"EUR 120","evidence":"x"}]'
    assert import_proposals(tenants_dir, 'heyzack', new, {'id1'}, source='task-new') == 1
    with (asks_dir / 'proposed.jsonl').open('a') as stream:
        stream.write(filler * 1000)
    assert import_proposals(tenants_dir, 'heyzack', old, {'id1'}, source='task-old') == 0
    last = [json.loads(line) for line in (asks_dir / 'proposed.jsonl').read_text().splitlines() if '"id1"' in line][-1]
    assert last['proposed'] == 'EUR 120' and last['source'] == 'task-new'


def test_unchanged_task_still_records_its_source(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    artifact = '[{"ask_id":"id1","proposed":"EUR 99"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}, source='task-a') == 1
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}, source='task-b') == 0
    journal = tenants_dir / 'heyzack' / 'asks' / 'proposed.jsonl'
    assert any(json.loads(l).get('source') == 'task-b' for l in journal.read_text().splitlines())
    # the receipt keeps task-b from being re-imported, even with a changed value
    assert import_proposals(tenants_dir, 'heyzack', '[{"ask_id":"id1","proposed":"EUR 5"}]', {'id1'}, source='task-b') == 0


def test_interrupted_import_is_retried_until_complete(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    asks_dir = tenants_dir / 'heyzack' / 'asks'
    asks_dir.mkdir(parents=True)
    # One row reached disk before the import stopped: no completion line, and a torn tail.
    (asks_dir / 'proposed.jsonl').write_text(
        json.dumps({'ask_id': 'id1', 'proposed': 'EUR 99', 'source': 'task-a', 'created': 10.0}) + '\n{"ask_id": "id2", "pro')
    artifact = '[{"ask_id":"id1","proposed":"EUR 99"},{"ask_id":"id2","proposed":"EUR 5"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2'}, source='task-a', created=10.0) == 1
    records = [json.loads(line) for line in (asks_dir / 'proposed.jsonl').read_text().splitlines()[2:]]
    assert records == [{'ask_id': 'id2', 'proposed': 'EUR 5', 'source': 'task-a', 'created': 10.0},
                       {'source': 'task-a', 'created': 10.0, 'complete': True}]
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1', 'id2'}, source='task-a', created=10.0) == 0


def test_older_task_imported_late_keeps_the_newer_proposal(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'heyzack').mkdir(parents=True)
    new = '[{"ask_id":"id1","proposed":"EUR 120"},{"ask_id":"id2","proposed":"yes"}]'
    old = '[{"ask_id":"id1","proposed":"EUR 99"},{"ask_id":"id3","proposed":"no"}]'
    assert import_proposals(tenants_dir, 'heyzack', new, {'id1', 'id2', 'id3'}, source='task-new', created=200.0) == 2
    # The older task still fills asks the newer one left open.
    assert import_proposals(tenants_dir, 'heyzack', old, {'id1', 'id2', 'id3'}, source='task-old', created=100.0) == 1
    from lib.tenant_asks import load_proposals
    assert load_proposals(tenants_dir / 'heyzack') == {'id1': 'EUR 120', 'id2': 'yes', 'id3': 'no'}


def test_journal_lines_from_before_completion_lines_count_as_imported(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    asks_dir = tenants_dir / 'heyzack' / 'asks'
    asks_dir.mkdir(parents=True)
    (asks_dir / 'proposed.jsonl').write_text(
        json.dumps({'ask_id': 'id1', 'proposed': 'EUR 120', 'source': 'task-new'}) + '\n'
        + json.dumps({'source': 'task-same', 'receipt': True}) + '\n')
    artifact = '[{"ask_id":"id1","proposed":"EUR 99"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}, source='task-new', created=1.0) == 0
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}, source='task-same', created=1.0) == 0


def test_imports_for_one_tenant_wait_for_the_journal_lock(tmp_path):
    import fcntl
    import threading
    tenants_dir = tmp_path / 'tenants'
    asks_dir = tenants_dir / 'heyzack' / 'asks'
    asks_dir.mkdir(parents=True)
    journal = asks_dir / 'proposed.jsonl'
    journal.write_text(json.dumps({'ask_id': 'id1', 'proposed': 'EUR 120', 'source': 'task-new', 'created': 200.0}) + '\n')
    result = []
    with journal.open('a') as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(target=lambda: result.append(import_proposals(
            tenants_dir, 'heyzack', '[{"ask_id":"id1","proposed":"EUR 99"}]', {'id1'}, source='task-old', created=100.0)))
        worker.start()
        worker.join(0.3)
        assert worker.is_alive() and journal.read_text().count('\n') == 1
        # A newer task lands while the older import waits; the older one must see it.
        held.write(json.dumps({'ask_id': 'id1', 'proposed': 'EUR 130', 'source': 'task-newest', 'created': 300.0}) + '\n')
        held.flush()
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
    worker.join(5)
    assert result == [0]
    from lib.tenant_asks import load_proposals
    assert load_proposals(tenants_dir / 'heyzack') == {'id1': 'EUR 130'}


def test_admit_refuses_templates_that_resolve_to_one_root(tmp_path):
    config = _base_config()
    _git_init(tmp_path)
    for name in ('tenant-a', 'tenant-b'):
        _git_init(tmp_path / name)
    # The shared parent is refused by its layout before the overlap check is even reached.
    with pytest.raises(ValueError, match='overlaps|outside the tenant layout'):
        admit(config, ['tenant-a', 'tenant-b'], 'org', 'founder', ['mac-coding-1'], root=str(tmp_path / '{tenant}' / '..'))


def test_admit_refuses_a_root_an_existing_project_already_uses(tmp_path):
    config = _base_config()
    _git_init(tmp_path / 'tenant-a')
    config['projects']['taken'] = {'tenant': 'taken', 'organization': 'org', 'runtimes': ['codex'],
                                   'root': str(tmp_path / 'tenant-a')}
    with pytest.raises(ValueError, match='overlaps the root of taken'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(tmp_path / '{tenant}'))


def test_admit_refuses_a_root_whose_git_history_holds_other_tenants(tmp_path):
    config = _base_config()
    clone = tmp_path / 'tenant-a'
    _git_init(clone)
    for name in ('tenant-a', 'other-tenant'):
        os.makedirs(clone / 'tenants' / name)
        (clone / 'tenants' / name / 'context.md').write_text(name)
    _git_commit_all(clone)
    # Only tenant-a is checked out now, but the other tenant's tree is still in .git.
    import shutil
    shutil.rmtree(clone / 'tenants' / 'other-tenant')
    _git_commit_all(clone, 'drop other tenant')
    with pytest.raises(ValueError, match='other tenants in its Git history'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(clone))


def test_admit_refuses_roots_whose_objects_live_elsewhere(tmp_path):
    config = _base_config()
    borrowed = tmp_path / 'tenant-a'
    _git_init(borrowed)
    (borrowed / '.git' / 'objects' / 'info' / 'alternates').write_text('/elsewhere/objects\n')
    with pytest.raises(ValueError, match='Cannot verify'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(borrowed))
    linked = tmp_path / 'tenant-b'
    linked.mkdir()
    (linked / '.git').write_text('gitdir: /elsewhere/.git/worktrees/x\n')
    with pytest.raises(ValueError, match='Cannot verify'):
        admit(config, ['tenant-b'], 'org', 'founder', ['mac-coding-1'], root=str(linked))


def test_admit_accepts_a_tenant_only_repository(tmp_path):
    config = _base_config()
    repo = tmp_path / 'tenant-a'
    _git_init(repo)
    (repo / 'MANIFEST.yaml').write_text('schema: snowgloves.manifest.v1\ntenant: tenant-a\n')
    (repo / 'context').mkdir()
    (repo / 'context' / 'offer.md').write_text('FILL: the price.')
    _git_commit_all(repo)
    assert admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(repo))['projects']['tenant-a']['root'] == str(repo)


@pytest.mark.parametrize('shared', ['fleet.yaml', 'nodes/mac-coding-1/node.yaml', '_audit/receipt.json',
                                    '.planning/STATE.md', 'specs/006-editorial-steward-integration/portfolio-map-proposal.json'])
def test_admit_refuses_a_root_carrying_shared_instance_data(tmp_path, shared):
    config = _base_config()
    root = tmp_path / 'tenant-a'
    _git_init(root)
    os.makedirs(root / 'tenants' / 'tenant-a')
    (root / 'tenants' / 'tenant-a' / 'MANIFEST.yaml').write_text('tenant: tenant-a')
    target = root / shared
    os.makedirs(target.parent, exist_ok=True)
    target.write_text('every tenant')
    _git_commit_all(root)
    with pytest.raises(ValueError, match='shared instance data'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))
    # Deleting it from the checkout is not enough while history still holds it.
    import shutil
    top = root / shared.split('/')[0]
    shutil.rmtree(top) if top.is_dir() else top.unlink()
    _git_commit_all(root, 'drop shared data')
    with pytest.raises(ValueError, match='shared instance data'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))


def test_import_refuses_a_tenant_directory_that_links_to_another_tenant(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'victim' / 'asks').mkdir(parents=True)
    (tenants_dir / 'intruder').symlink_to(tenants_dir / 'victim', target_is_directory=True)
    artifact = '[{"ask_id":"id1","proposed":"EUR 99"}]'
    assert import_proposals(tenants_dir, 'intruder', artifact, {'id1'}, source='task-x') == 0
    assert not (tenants_dir / 'victim' / 'asks' / 'proposed.jsonl').exists()
    for bad in ('..', '.', '', 'a/b'):
        assert import_proposals(tenants_dir, bad, artifact, {'id1'}, source='task-y') == 0
    assert not (tmp_path / 'asks').exists()


@pytest.mark.parametrize('remove_after', [False, True])
def test_admit_refuses_a_root_that_tracks_a_symlink(tmp_path, remove_after):
    config = _base_config()
    root = tmp_path / 'tenant-a'
    _git_init(root)
    (root / 'context').mkdir()
    (root / 'context' / 'offer.md').write_text('FILL: the price.')
    (root / 'shared').symlink_to(tmp_path)
    _git_commit_all(root)
    if remove_after:
        # History alone is enough: any worker can check the old commit out.
        (root / 'shared').unlink()
        _git_commit_all(root, 'drop link')
    with pytest.raises(ValueError, match='symlink'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))


def test_import_never_follows_an_asks_directory_link(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    (tenants_dir / 'victim' / 'asks').mkdir(parents=True)
    (tenants_dir / 'intruder').mkdir()
    (tenants_dir / 'intruder' / 'asks').symlink_to(tenants_dir / 'victim' / 'asks', target_is_directory=True)
    assert import_proposals(tenants_dir, 'intruder', '[{"ask_id":"id1","proposed":"EUR 99"}]', {'id1'}, source='task-x') == 0
    assert not (tenants_dir / 'victim' / 'asks' / 'proposed.jsonl').exists()


def test_import_scan_skips_an_oversized_line_and_still_sees_completion(tmp_path):
    tenants_dir = tmp_path / 'tenants'
    asks_dir = tenants_dir / 'heyzack' / 'asks'
    asks_dir.mkdir(parents=True)
    (asks_dir / 'proposed.jsonl').write_text(
        '{"ask_id": "id9", "proposed": "' + 'x' * 200000 + '"}\n'
        + json.dumps({'ask_id': 'id1', 'proposed': 'EUR 99', 'source': 'task-a', 'created': 5.0}) + '\n'
        + json.dumps({'source': 'task-a', 'created': 5.0, 'complete': True}) + '\n')
    artifact = '[{"ask_id":"id1","proposed":"EUR 99"}]'
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}, source='task-a', created=5.0) == 0
    # A new task with the same value is deduped against the line after the oversized one.
    assert import_proposals(tenants_dir, 'heyzack', artifact, {'id1'}, source='task-b', created=6.0) == 0


@pytest.mark.parametrize('borrow', ['git-link', 'objects-link', 'commondir', 'shard-link', 'pack-link'])
def test_admit_refuses_a_root_whose_git_metadata_lives_elsewhere(tmp_path, borrow):
    config = _base_config()
    other = tmp_path / 'other-repo'
    _git_init(other)
    root = tmp_path / 'tenant-a'
    root.mkdir()
    if borrow == 'git-link':
        (root / '.git').symlink_to(other / '.git', target_is_directory=True)
    else:
        _git_init(root)
        if borrow == 'objects-link':
            import shutil
            shutil.rmtree(root / '.git' / 'objects')
            (root / '.git' / 'objects').symlink_to(other / '.git' / 'objects', target_is_directory=True)
        elif borrow == 'commondir':
            (root / '.git' / 'commondir').write_text(str(other / '.git') + '\n')
        elif borrow == 'shard-link':
            # Git follows a linked loose-object shard into the other repository.
            (other / 'blob.txt').write_text('other tenant')
            subprocess.run(['git', '-C', str(other), 'add', 'blob.txt'], check=True)
            shard = next(p for p in (other / '.git' / 'objects').iterdir() if len(p.name) == 2)
            (root / '.git' / 'objects' / shard.name).symlink_to(shard, target_is_directory=True)
        else:
            (root / '.git' / 'objects' / 'pack' / 'pack-x.pack').symlink_to(other / '.git' / 'HEAD')
    with pytest.raises(ValueError, match='Cannot verify'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))


@pytest.mark.parametrize('key, value', [('core.hooksPath', '/elsewhere/hooks'), ('core.fsmonitor', '/bin/sh -c id'),
                                        ('filter.x.smudge', 'cat /etc/hosts'), ('include.path', '/elsewhere/config')])
def test_admit_refuses_a_root_whose_git_config_could_run_commands(tmp_path, key, value):
    config = _base_config()
    root = tmp_path / 'tenant-a'
    _git_init(root)
    subprocess.run(['git', '-C', str(root), 'config', key, value], check=True)
    with pytest.raises(ValueError, match='Git config that could run commands'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))
    subprocess.run(['git', '-C', str(root), 'config', '--unset', key], check=True)
    subprocess.run(['git', '-C', str(root), 'config', 'remote.origin.url', '/srv/tenant-a.git'], check=True)
    assert 'tenant-a' in admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))['projects']


def test_import_never_follows_a_linked_tenants_directory(tmp_path):
    real = tmp_path / 'outside'
    (real / 'heyzack' / 'asks').mkdir(parents=True)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'tenants').symlink_to(real, target_is_directory=True)
    assert import_proposals(data / 'tenants', 'heyzack', '[{"ask_id":"id1","proposed":"EUR 99"}]', {'id1'}, source='t') == 0
    assert not (real / 'heyzack' / 'asks' / 'proposed.jsonl').exists()


@pytest.mark.parametrize('nested', ['backup/fleet.yaml', 'archive/nodes/mac-coding-1/node.yaml', 'context/old/specs/x.json'])
def test_admit_refuses_shared_instance_data_at_any_depth(tmp_path, nested):
    config = _base_config()
    root = tmp_path / 'tenant-a'
    _git_init(root)
    target = root / nested
    os.makedirs(target.parent, exist_ok=True)
    target.write_text('every tenant')
    _git_commit_all(root)
    with pytest.raises(ValueError, match='shared instance data'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))


def test_admit_refuses_entries_outside_the_tenant_layout(tmp_path):
    config = _base_config()
    root = tmp_path / 'tenant-a'
    _git_init(root)
    (root / 'context').mkdir()
    (root / 'context' / 'offer.md').write_text('FILL: the price.')
    (root / 'portfolio-dump.json').write_text('{}')
    _git_commit_all(root)
    with pytest.raises(ValueError, match='outside the tenant layout'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(root))


@pytest.mark.parametrize('earlier', ['tenant: tenant-b\n', None])
def test_admit_refuses_a_root_level_repository_reused_from_another_tenant(tmp_path, earlier):
    config = _base_config()
    repo = tmp_path / 'tenant-a'
    _git_init(repo)
    (repo / 'context').mkdir()
    (repo / 'context' / 'offer.md').write_text('FILL: tenant-b private plan.')
    if earlier is not None:
        (repo / 'MANIFEST.yaml').write_text(earlier)
    _git_commit_all(repo)
    # The current commit is tenant-a's, but the earlier one is still readable via git show.
    (repo / 'MANIFEST.yaml').write_text('tenant: tenant-a\n')
    (repo / 'context' / 'offer.md').write_text('FILL: the price.')
    _git_commit_all(repo, 'now tenant-a')
    with pytest.raises(ValueError, match='MANIFEST.yaml does not name tenant-a'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(repo))


def _tenant_repo(tmp_path, manifest='tenant: tenant-a\n'):
    repo = tmp_path / 'tenant-a'
    _git_init(repo)
    (repo / 'MANIFEST.yaml').write_text(manifest)
    (repo / 'context').mkdir()
    (repo / 'context' / 'offer.md').write_text('FILL: the price.')
    _git_commit_all(repo)
    return repo


@pytest.mark.parametrize('tag', ['blob', 'annotated'])
def test_admit_refuses_refs_that_are_not_commits(tmp_path, tag):
    config = _base_config()
    repo = _tenant_repo(tmp_path)
    if tag == 'blob':
        blob = subprocess.run(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'], input=b'tenant-b private plan',
                              check=True, capture_output=True).stdout.decode().strip()
        subprocess.run(['git', '-C', str(repo), 'tag', 'stash', blob], check=True)
    else:
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                        'tag', '-a', 'v1', '-m', 'tenant-b private plan'], check=True)
    with pytest.raises(ValueError, match='Cannot verify'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(repo))


@pytest.mark.parametrize('manifest', ['tenant: tenant-a\ntenant: tenant-b\n', 'base: &t tenant-a\ntenant: *t\n',
                                      'tenant: [tenant-a\n'])
def test_admit_refuses_ambiguous_or_malformed_manifests(tmp_path, manifest):
    config = _base_config()
    repo = _tenant_repo(tmp_path, manifest)
    with pytest.raises(ValueError, match='MANIFEST.yaml does not name tenant-a'):
        admit(config, ['tenant-a'], 'org', 'founder', ['mac-coding-1'], root=str(repo))
