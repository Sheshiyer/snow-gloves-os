"""Tests for tenant admission, kickoff briefs and proposal import."""
import json
import os
import tempfile
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fleet_kickoff
from fleet_admit_tenants import admit, _write_config
from fleet_kickoff import kickoff_brief, _task_body
from fleet_asks_import import import_proposals, _last_json_array


GIT_ROOT = tempfile.mkdtemp(prefix='admit-root-')
os.makedirs(os.path.join(GIT_ROOT, '.git'), exist_ok=True)


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
        'tenant': 'tryambakam', 'organization': 'new-org', 'runtimes': ['codex'], 'root': GIT_ROOT}


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
    result = admit(config, ['tryambakam'], 'org', 'founder', ['mac-creative'])
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
