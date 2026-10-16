"""Tests for tenant admission, kickoff briefs and proposal import."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_admit_tenants import admit
from fleet_kickoff import kickoff_brief
from fleet_asks_import import import_proposals


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
    result = admit(config, ['heyzack', 'tryambakam'], 'new-org', 'founder', ['mac-coding-1'])
    assert 'heyzack' not in result['projects']
    assert result['projects']['snowgloves']['tenant'] == 'heyzack'
    assert result['projects']['tryambakam'] == {
        'tenant': 'tryambakam', 'organization': 'new-org', 'runtimes': ['codex']}


def test_admit_appends_to_principal_and_workers():
    config = _base_config()
    result = admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'])
    assert 'tryambakam' in result['principals']['founder']['projects']
    assert 'tryambakam' in result['workers']['mac-coding-1']['projects']


def test_admit_never_adds_write_grants():
    config = _base_config()
    result = admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'])
    project = result['projects']['tryambakam']
    assert 'write' not in project
    assert 'fanout' not in project
    assert 'write_projects' not in result['principals']['founder']


def test_admit_is_idempotent():
    config = _base_config()
    result = admit(config, ['heyzack', 'tryambakam'], 'org', 'founder', ['mac-coding-1'])
    result2 = admit(result, ['heyzack', 'tryambakam'], 'org', 'founder', ['mac-coding-1'])
    assert result2 == result


def test_admit_does_not_mutate_input():
    config = _base_config()
    admit(config, ['tryambakam'], 'org', 'founder', ['mac-coding-1'])
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
