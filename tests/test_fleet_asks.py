"""Coordinator ask listing, answering and the append-only answer journal."""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.fleet_coordinator import Coordinator, Rejected, server
from test_fleet_coordinator import fleet  # noqa: F401


@pytest.fixture
def asks_ctx(fleet, monkeypatch):
    c, config, clock = fleet
    config['principals']['approver'] = {
        'token': 'approver-token', 'projects': ['snowgloves'], 'permissions': ['read', 'approve'],
    }
    monkeypatch.setenv('SNOWGLOVES_DATA', config['data_root'])
    tenant = Path(config['data_root']) / 'tenants' / 'heyzack'
    (tenant / 'context').mkdir(parents=True)
    (tenant / 'context' / 'offer.md').write_text('# Offer\nFILL: the price.\n')
    return c, config, clock, tenant


def _ask_id(c, config):
    return c.asks.list('founder', config['principals']['founder'], 'snowgloves')['asks'][0]['id']


def test_list_needs_read_and_project_scope(asks_ctx):
    c, config, *_ = asks_ctx
    listed = c.asks.list('founder', config['principals']['founder'], 'snowgloves')
    assert [a['kind'] for a in listed['asks']] == ['fact']
    assert listed['asks'][0]['status'] == 'open'
    assert listed['asks'][0]['answer'] is None
    assert set(listed['asks'][0]) == {
        'id', 'tenant', 'kind', 'role', 'title', 'source', 'answer_type', 'proposed',
        'project', 'status', 'answer', 'answered', 'answered_by'}
    with pytest.raises(Rejected) as error:
        c.asks.list('outsider', config['principals']['outsider'], 'snowgloves')
    assert error.value.status == 403


def test_answer_requires_approve(asks_ctx):
    c, config, *_ = asks_ctx
    target = _ask_id(c, config)
    with pytest.raises(Rejected) as error:
        c.asks.answer('founder', config['principals']['founder'], 'snowgloves', target, {'value': 'EUR 99'})
    assert error.value.status == 403
    result = c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    assert result['ask']['status'] == 'answered'
    assert result['ask']['answer'] == {'value': 'EUR 99'}
    assert result['ask']['answered_by'] == 'approver'
    assert isinstance(result['ask']['answered'], float)


def test_answer_shape_matches_type(asks_ctx):
    c, config, *_ = asks_ctx
    target = _ask_id(c, config)
    for body in ({'accept': True}, {'value': 'x' * 501}, {'value': 'my token is abc'}, {}, {'value': 'line one\nline two'}, {'value': 'tab\there'}):
        with pytest.raises(Rejected) as error:
            c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, body)
        assert error.value.status == 400


def test_unknown_or_vanished_ask_404(asks_ctx):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    with pytest.raises(Rejected) as error:
        c.asks.answer('approver', config['principals']['approver'], 'snowgloves', 'f' * 32, {'value': 'EUR 99'})
    assert error.value.status == 404
    (tenant / 'context' / 'offer.md').write_text('# Offer\nEUR 99\n')
    with pytest.raises(Rejected) as error:
        c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    assert error.value.status == 404


def test_answer_persisted_and_journaled(asks_ctx):
    c, config, clock, tenant = asks_ctx
    target = _ask_id(c, config)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    second = Coordinator(config, clock=lambda: clock[0])
    try:
        listed = second.asks.list('founder', config['principals']['founder'], 'snowgloves')
        assert listed['asks'][0]['status'] == 'answered'
        assert listed['asks'][0]['answer'] == {'value': 'EUR 99'}
    finally:
        second.close()
    lines = (tenant / 'asks' / 'answers.jsonl').read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record['ask_id'] == target
    assert record['answered_by'] == 'approver'
    assert record['answer'] == {'value': 'EUR 99'}
    assert set(record) == {'ask_id', 'project', 'tenant', 'kind', 'title', 'answer', 'answered', 'answered_by'}


def test_reanswer_updates_and_appends(asks_ctx):
    c, config, _, tenant = asks_ctx
    approver = config['principals']['approver']
    target = _ask_id(c, config)
    c.asks.answer('approver', approver, 'snowgloves', target, {'value': 'EUR 80'})
    result = c.asks.answer('approver', approver, 'snowgloves', target, {'value': 'EUR 99'})
    assert result['ask']['answer'] == {'value': 'EUR 99'}
    listed = c.asks.list('founder', config['principals']['founder'], 'snowgloves')
    assert listed['asks'][0]['answer'] == {'value': 'EUR 99'}
    lines = (tenant / 'asks' / 'answers.jsonl').read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])['answer'] == {'value': 'EUR 80'}
    assert json.loads(lines[1])['answer'] == {'value': 'EUR 99'}


def test_journal_refuses_symlink(asks_ctx, tmp_path):
    c, config, _, tenant = asks_ctx
    outside = tmp_path / 'outside-asks'
    outside.mkdir()
    (tenant / 'asks').symlink_to(outside, target_is_directory=True)
    target = _ask_id(c, config)
    with pytest.raises(Rejected) as error:
        c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    assert error.value.status == 503
    assert list(outside.iterdir()) == []
    assert c.db.execute('SELECT count(*) FROM ask_answers').fetchone()[0] == 0


def test_http_routes(asks_ctx):
    c, config, *_ = asks_ctx
    http = server(c, 0)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    endpoint = 'http://127.0.0.1:%d' % http.server_port

    def request(path, token=None, body=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(endpoint + path,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    try:
        listed = request('/v1/asks/snowgloves', 'founder-secret-token')
        assert len(listed['asks']) == 1
        target = listed['asks'][0]['id']
        answered = request('/v1/asks/snowgloves/%s/answer' % target, 'approver-token', {'value': 'EUR 99'})
        assert answered['ask']['status'] == 'answered'
        with pytest.raises(urllib.error.HTTPError) as error:
            request('/v1/asks/snowgloves/notanid/answer', 'approver-token', {'value': 'x'})
        assert error.value.code == 404
    finally:
        http.shutdown()
        http.server_close()
