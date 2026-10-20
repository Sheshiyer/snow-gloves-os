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
    for body in ({'accept': True}, {'value': 'x' * 501}, {'value': 'my token is abc'}, {}, {'value': 'line one\nline two'}, {'value': 'tab\there'}, {'value': '   '}, {'value': 'bad \ud800 surrogate'}):
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
    assert set(record) == {'answer_id', 'ask_id', 'project', 'tenant', 'kind', 'title', 'answer', 'proposed', 'answered', 'answered_by'}


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


def test_answered_text_ask_keeps_its_shape_when_a_proposal_arrives(asks_ctx):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    (tenant / 'asks' / 'proposed.jsonl').write_text(json.dumps({'ask_id': target, 'proposed': 'EUR 120'}) + '\n')
    listed = {a['id']: a for a in c.asks.list('founder', config['principals']['founder'], 'snowgloves')['asks']}
    assert listed[target]['answer_type'] == 'text' and listed[target]['proposed'] is None
    assert listed[target]['answer'] == {'value': 'EUR 99'}
    again = c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 100'})
    assert again['ask']['answer'] == {'value': 'EUR 100'}


def test_journal_is_appended_only_after_the_database_commit(asks_ctx, monkeypatch):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    original = c.asks._append_journal
    seen = []
    def spy(path, record):
        seen.append(c.db.in_transaction)
        return original(path, record)
    monkeypatch.setattr(c.asks, '_append_journal', spy)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    assert seen == [False]
    line = json.loads((tenant / 'asks' / 'answers.jsonl').read_text().splitlines()[0])
    assert len(line['answer_id']) == 32


def test_failed_journal_append_is_retried_from_the_outbox(asks_ctx, monkeypatch):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    original = c.asks._append_journal
    calls = {'n': 0}
    def flaky(path, record):
        calls['n'] += 1
        if calls['n'] == 1:
            raise Rejected(503, 'Ask journal unavailable')
        return original(path, record)
    monkeypatch.setattr(c.asks, '_append_journal', flaky)
    result = c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    assert result['ask']['status'] == 'answered'
    assert not (tenant / 'asks' / 'answers.jsonl').exists()
    c.asks.list('founder', config['principals']['founder'], 'snowgloves')
    assert len((tenant / 'asks' / 'answers.jsonl').read_text().splitlines()) == 1
    assert c.db.execute('SELECT count(*) FROM ask_journal_outbox').fetchone()[0] == 0


def test_answered_by_is_bounded_for_the_client(asks_ctx):
    c, config, *_ = asks_ctx
    name = 'p' * 150 + '\x07'
    config['principals'][name] = {'token': 'long-token', 'projects': ['snowgloves'], 'permissions': ['read', 'approve']}
    target = _ask_id(c, config)
    result = c.asks.answer(name, config['principals'][name], 'snowgloves', target, {'value': 'EUR 99'})
    by = result['ask']['answered_by']
    assert 0 < len(by) <= 120 and not any(ord(ch) < 32 for ch in by)


def test_concurrent_flushes_append_each_record_once(asks_ctx, monkeypatch):
    import time
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    original = c.asks._append_journal
    state = {'fail': True}
    def slow(path, record):
        if state['fail']:
            raise Rejected(503, 'Ask journal unavailable')
        time.sleep(0.05)
        return original(path, record)
    monkeypatch.setattr(c.asks, '_append_journal', slow)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 100'})
    state['fail'] = False
    threads = [threading.Thread(target=c.asks.flush) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    values = [json.loads(line)['answer']['value'] for line in (tenant / 'asks' / 'answers.jsonl').read_text().splitlines()]
    assert values == ['EUR 99', 'EUR 100']


def test_yes_no_answer_keeps_the_proposal_it_answered(asks_ctx):
    c, config, clock, tenant = asks_ctx
    target = _ask_id(c, config)
    (tenant / 'asks').mkdir(exist_ok=True)
    (tenant / 'asks' / 'proposed.jsonl').write_text(json.dumps({'ask_id': target, 'proposed': 'EUR 99'}) + '\n')
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'accept': True, 'proposed': 'EUR 99'})
    (tenant / 'asks' / 'proposed.jsonl').write_text('')
    listed = {a['id']: a for a in c.asks.list('founder', config['principals']['founder'], 'snowgloves')['asks']}
    assert listed[target]['answer_type'] == 'yes_no' and listed[target]['proposed'] == 'EUR 99'
    assert listed[target]['answer'] == {'accept': True}
    record = json.loads((tenant / 'asks' / 'answers.jsonl').read_text().splitlines()[-1])
    assert record['proposed'] == 'EUR 99'
    second = Coordinator(config, clock=lambda: clock[0])
    try:
        again = {a['id']: a for a in second.asks.list('founder', config['principals']['founder'], 'snowgloves')['asks']}
        assert again[target]['proposed'] == 'EUR 99'
    finally:
        second.close()


def test_partial_journal_tail_is_repaired_before_append(asks_ctx):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    journal = tenant / 'asks' / 'answers.jsonl'
    with journal.open('ab') as stream:
        stream.write(b'{"answer_id":"partial","ask')
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 100'})
    lines = journal.read_text().splitlines()
    assert [json.loads(line)['answer']['value'] for line in lines] == ['EUR 99', 'EUR 100']


def test_principal_names_with_lone_surrogates_still_journal(asks_ctx):
    c, config, _, tenant = asks_ctx
    name = 'appro\ud800ver'
    config['principals'][name] = {'token': 'odd-token', 'projects': ['snowgloves'], 'permissions': ['read', 'approve']}
    target = _ask_id(c, config)
    result = c.asks.answer(name, config['principals'][name], 'snowgloves', target, {'value': 'EUR 99'})
    result['ask']['answered_by'].encode('utf-8')
    assert c.db.execute('SELECT count(*) FROM ask_journal_outbox').fetchone()[0] == 0
    assert len((tenant / 'asks' / 'answers.jsonl').read_text().splitlines()) == 1


def test_unencodable_record_never_blocks_the_outbox(asks_ctx):
    c, config, _, tenant = asks_ctx
    path = c.asks._journal_path('heyzack')
    c.asks._append_journal(path, {'answer_id': 'x', 'title': 'bad \ud800'})
    line = (tenant / 'asks' / 'answers.jsonl').read_text().splitlines()[0]
    assert json.loads(line)['answer_id'] == 'x'


def test_retry_after_a_crash_between_append_and_delete_appends_once(asks_ctx):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    journal = tenant / 'asks' / 'answers.jsonl'
    record = json.loads(journal.read_text().splitlines()[-1])
    # The record reached the journal, but the process died before its outbox row was deleted.
    with c.transaction():
        c.db.execute('INSERT INTO ask_journal_outbox(answer_id, tenant, record_json, created) VALUES(?, ?, ?, ?)',
                     (record['answer_id'], record['tenant'], json.dumps(record, sort_keys=True), record['answered']))
    c.asks.flush()
    assert [json.loads(line)['answer_id'] for line in journal.read_text().splitlines()] == [record['answer_id']]
    assert c.db.execute('SELECT count(*) FROM ask_journal_outbox').fetchone()[0] == 0


def test_journal_append_never_follows_a_swapped_asks_directory(asks_ctx, tmp_path):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    path = c.asks._journal_path(tenant.name)  # validated while still a real directory
    # Another process swaps asks/ for a link to somewhere else after validation.
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    import shutil
    shutil.rmtree(tenant / 'asks')
    (tenant / 'asks').symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(Rejected):
        c.asks._append_journal(path, {'answer_id': 'x', 'ask_id': target})
    assert not (elsewhere / 'answers.jsonl').exists()


def test_journal_append_never_follows_a_swapped_tenants_directory(asks_ctx, tmp_path):
    c, config, _, tenant = asks_ctx
    path = c.asks._journal_path(tenant.name)
    tenants = tenant.parent
    moved = tmp_path / 'moved-tenants'
    tenants.rename(moved)
    tenants.symlink_to(moved, target_is_directory=True)
    try:
        with pytest.raises(Rejected):
            c.asks._append_journal(path, {'answer_id': 'x'})
        assert not (moved / tenant.name / 'asks' / 'answers.jsonl').exists()
    finally:
        tenants.unlink()
        moved.rename(tenants)


def test_asks_directory_is_never_created_through_a_linked_tenant(asks_ctx, tmp_path):
    c, config, _, tenant = asks_ctx
    import shutil
    shutil.rmtree(tenant / 'asks', ignore_errors=True)
    outside = tmp_path / 'outside-tenant'
    outside.mkdir()
    moved = tmp_path / 'real-tenant'
    tenant.rename(moved)
    tenant.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(Rejected):
            c.asks._journal_path(tenant.name)
        with pytest.raises(OSError):
            c.asks._hold_asks(tenant / 'asks' / 'answers.jsonl')
        assert not (outside / 'asks').exists()
    finally:
        tenant.unlink()
        moved.rename(tenant)


def test_journal_path_never_follows_a_linked_tenants_directory(asks_ctx, tmp_path):
    c, config, _, tenant = asks_ctx
    tenants = tenant.parent
    moved = tmp_path / 'moved'
    tenants.rename(moved)
    outside = tmp_path / 'outside'
    (outside / tenant.name).mkdir(parents=True)
    tenants.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(Rejected):
            c.asks._journal_path(tenant.name)
        assert not (outside / tenant.name / 'asks').exists()
    finally:
        tenants.unlink()
        moved.rename(tenants)


def test_yes_no_answer_is_refused_when_the_proposal_changed(asks_ctx):
    c, config, clock, tenant = asks_ctx
    target = _ask_id(c, config)
    (tenant / 'asks').mkdir(exist_ok=True)
    (tenant / 'asks' / 'proposed.jsonl').write_text(json.dumps({'ask_id': target, 'proposed': 'EUR 120'}) + '\n')
    # The founder saw EUR 99; a newer import replaced it before the click.
    for body in ({'accept': True, 'proposed': 'EUR 99'}, {'accept': True}):
        with pytest.raises(Rejected) as exc:
            c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, body)
        assert exc.value.status == 409
    assert not (tenant / 'asks' / 'answers.jsonl').exists() or (tenant / 'asks' / 'answers.jsonl').read_text() == ''
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'accept': False, 'proposed': 'EUR 120'})


def test_a_damaged_journal_tail_is_refused_without_a_full_backward_scan(asks_ctx):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    path = c.asks._journal_path(tenant.name)
    path.write_bytes(b'{"answer_id":"old"}\n' + b'x' * (200 * 1024))
    with pytest.raises(Rejected):
        c.asks._append_journal(path, {'answer_id': 'new', 'ask_id': target})
    # Nothing was cut or appended; the outbox keeps the answer for repair.
    assert path.read_bytes().endswith(b'x' * 1024) and b'"new"' not in path.read_bytes()


def test_listing_loads_answers_only_for_current_asks(asks_ctx):
    c, config, _, tenant = asks_ctx
    target = _ask_id(c, config)
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    # Answers to asks that no longer exist (edited FILL lines) stay stored.
    with c.transaction():
        c.db.executemany('INSERT INTO ask_answers(project, ask_id, tenant, kind, answer_json, answered, answered_by, proposed) '
                         'VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
                         [('snowgloves', '%032x' % n, 'heyzack', 'fact', '{"value":"old"}', 1.0, 'x', None) for n in range(500)])
    statements = []
    c.db.set_trace_callback(statements.append)
    try:
        listed = c.asks.list('founder', config['principals']['founder'], 'snowgloves')['asks']
    finally:
        c.db.set_trace_callback(None)
    assert [a['answer'] for a in listed] == [{'value': 'EUR 99'}]
    lookups = [s for s in statements if 'FROM ask_answers' in s]
    assert lookups and all('ask_id IN' in s for s in lookups)


def test_outbox_flushes_in_batches_and_skips_a_blocked_tenant_in_the_query(asks_ctx, monkeypatch):
    import lib.fleet_asks as fleet_asks
    c, config, _, tenant = asks_ctx
    monkeypatch.setattr(fleet_asks, 'FLUSH_BATCH', 2)
    rows = [('gone-%d' % n, 'missing-tenant') for n in range(5)] + [('ok-%d' % n, 'heyzack') for n in range(3)]
    with c.transaction():
        c.db.executemany('INSERT INTO ask_journal_outbox(answer_id, tenant, record_json, created) VALUES(?, ?, ?, ?)',
                         [(answer_id, owner, json.dumps({'answer_id': answer_id, 'tenant': owner}), 1.0) for answer_id, owner in rows])
    attempts = []
    original = c.asks._append_journal
    monkeypatch.setattr(c.asks, '_append_journal', lambda path, record: (attempts.append(record['answer_id']), original(path, record))[1])
    statements = []
    c.db.set_trace_callback(statements.append)
    try:
        c.asks.flush()
    finally:
        c.db.set_trace_callback(None)
    # The tenant with no journal fails at its first row; the query then skips its later rows.
    assert [a for a in attempts if a.startswith('gone')] == []
    assert [a for a in attempts if a.startswith('ok')] == ['ok-0', 'ok-1', 'ok-2']
    assert sorted(r[0] for r in c.db.execute('SELECT answer_id FROM ask_journal_outbox')) == ['gone-%d' % n for n in range(5)]
    reads = [s for s in statements if 'FROM ask_journal_outbox' in s and s.lstrip().upper().startswith('SELECT')]
    assert reads and all('LIMIT' in s for s in reads) and any('NOT IN' in s for s in reads)


def test_a_decision_answer_does_not_carry_over_to_revised_text(asks_ctx):
    c, config, _, tenant = asks_ctx
    spec = Path(config['data_root']) / 'specs' / '006-editorial-steward-integration'
    spec.mkdir(parents=True)
    def propose(description):
        (spec / 'portfolio-map-proposal.json').write_text(json.dumps({'cross_brand_flows': [
            {'id': 'f1', 'status': 'proposed_not_approved', 'participants': ['heyzack'], 'description': description}]}))
    def decision():
        listed = c.asks.list('founder', config['principals']['founder'], 'snowgloves')['asks']
        return [a for a in listed if a['kind'] == 'decision'][0]
    propose('Share leads with acme')
    old = decision()['id']
    c.asks.answer('approver', config['principals']['approver'], 'snowgloves', old, {'accept': True})
    assert decision()['status'] == 'answered'
    propose('Share leads and revenue with acme')
    revised = decision()
    assert revised['id'] != old and revised['status'] == 'open' and revised['answer'] is None
    # A click still bound to the old wording no longer reaches any ask.
    with pytest.raises(Rejected) as error:
        c.asks.answer('approver', config['principals']['approver'], 'snowgloves', old, {'accept': True})
    assert error.value.status == 404


def test_one_flush_appends_a_bounded_number_of_rows_and_leaves_the_rest_queued(asks_ctx, monkeypatch):
    import lib.fleet_asks as fleet_asks
    c, config, _, tenant = asks_ctx
    monkeypatch.setattr(fleet_asks, 'MAX_FLUSH_ROWS', 3)
    with c.transaction():
        c.db.executemany('INSERT INTO ask_journal_outbox(answer_id, tenant, record_json, created) VALUES(?, ?, ?, ?)',
                         [('a%d' % n, 'heyzack', json.dumps({'answer_id': 'a%d' % n, 'tenant': 'heyzack'}), 1.0) for n in range(7)])
    journal = tenant / 'asks' / 'answers.jsonl'
    written = lambda: [json.loads(line)['answer_id'] for line in journal.read_text().splitlines()] if journal.exists() else []
    # A backlog drains over several calls, in order, never all at once.
    c.asks.flush()
    assert written() == ['a0', 'a1', 'a2']
    c.asks.flush()
    c.asks.flush()
    assert written() == ['a%d' % n for n in range(7)]
    assert c.db.execute('SELECT count(*) FROM ask_journal_outbox').fetchone()[0] == 0
    # The time budget stops a call too.
    monkeypatch.setattr(fleet_asks, 'MAX_FLUSH_ROWS', 500)
    monkeypatch.setattr(fleet_asks, 'FLUSH_SECONDS', -1)
    with c.transaction():
        c.db.execute('INSERT INTO ask_journal_outbox(answer_id, tenant, record_json, created) VALUES(?, ?, ?, ?)',
                     ('late', 'heyzack', json.dumps({'answer_id': 'late', 'tenant': 'heyzack'}), 1.0))
    c.asks.flush()
    assert 'late' not in written()


def test_a_hard_linked_answer_journal_is_never_written(asks_ctx, tmp_path):
    import os as system
    c, config, _, tenant = asks_ctx
    precious = tmp_path / 'precious.json'
    precious.write_text('{"keep": "this"}')
    (tenant / 'asks').mkdir(exist_ok=True)
    # answers.jsonl shares an inode with an unrelated private file.
    system.link(precious, tenant / 'asks' / 'answers.jsonl')
    target = _ask_id(c, config)
    result = c.asks.answer('approver', config['principals']['approver'], 'snowgloves', target, {'value': 'EUR 99'})
    # The answer is recorded in SQLite; the journal write is refused and stays queued.
    assert result['ask']['status'] == 'answered'
    assert precious.read_text() == '{"keep": "this"}'
    assert c.db.execute('SELECT count(*) FROM ask_journal_outbox').fetchone()[0] == 1
