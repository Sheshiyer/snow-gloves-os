"""Founder asks derived from tenant files: bounded, sensitive-safe, never raising."""
import json
import re
from pathlib import Path

import yaml

from lib.tenant_asks import SENSITIVE_RE, load_catalog, load_proposals, ASK_KINDS, ROLE_FOR_KIND, ask_id, derive_asks, load_proposal


def test_ask_kinds_and_roles():
    assert ASK_KINDS == ('fact', 'decision', 'connect', 'website', 'brand')
    assert ROLE_FOR_KIND == {
        'fact': 'librarian',
        'decision': 'chief-of-staff',
        'connect': 'dispatcher',
        'website': 'interpreter',
        'brand': 'interpreter',
    }


def test_fill_lines_become_fact_asks(tmp_path):
    t = tmp_path / 'heyzack'
    (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    (t / 'context/open-questions.md').write_text('- FILL: the price.\n')
    asks = derive_asks(tmp_path, 'heyzack')
    assert [(a['kind'], a['role'], a['title'], a['source'], a['answer_type']) for a in asks] == [
        ('fact', 'librarian', 'the price.', 'context/offer.md', 'text')]
    assert asks[0]['id'] == ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    assert set(asks[0]) == {'id', 'tenant', 'kind', 'role', 'title', 'source', 'answer_type', 'proposed'}
    assert asks[0]['tenant'] == 'heyzack' and asks[0]['proposed'] is None


def test_fill_wording_change_rotates_id(tmp_path):
    t = tmp_path / 'heyzack'
    (t / 'context').mkdir(parents=True)
    offer = t / 'context/offer.md'
    offer.write_text('FILL: the price.\n')
    old = derive_asks(tmp_path, 'heyzack')[0]
    offer.write_text('FILL: the final price.\n')
    new = derive_asks(tmp_path, 'heyzack')[0]
    assert old['id'] == ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    assert new['id'] == ask_id('heyzack', 'fact', 'context/offer.md|the final price.')
    assert old['id'] != new['id']
    assert [a['id'] for a in derive_asks(tmp_path, 'heyzack')] == [new['id']]


def test_context_symlink_yields_no_fact_asks(tmp_path):
    t = tmp_path / 'heyzack'
    t.mkdir()
    real = tmp_path / 'real-context'
    real.mkdir()
    (real / 'offer.md').write_text('FILL: the price.\n')
    (t / 'context').symlink_to(real, target_is_directory=True)
    assert derive_asks(tmp_path, 'heyzack') == []


def test_proposed_value_turns_fact_into_yes_no(tmp_path):
    t = tmp_path / 'heyzack'
    (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('FILL: the price.\n')
    ask = derive_asks(tmp_path, 'heyzack')[0]
    assert ask['answer_type'] == 'text' and ask['proposed'] is None

    (t / 'asks').mkdir()
    (t / 'asks/proposed.jsonl').write_text(
        json.dumps({'ask_id': ask['id'], 'proposed': 'EUR 80'}) + '\n'
        + json.dumps({'ask_id': ask['id'], 'proposed': 'EUR 99'}) + '\n')
    asks = derive_asks(tmp_path, 'heyzack')
    assert len(asks) == 1
    assert asks[0]['answer_type'] == 'yes_no'
    assert asks[0]['proposed'] == 'EUR 99'


def test_decision_connect_website_brand(tmp_path):
    tenants = tmp_path / 'tenants'
    t = tenants / 'heyzack'
    t.mkdir(parents=True)
    (t / 'sources.yaml').write_text(yaml.safe_dump({
        'tenant': 'heyzack',
        'sources': [{'id': 'drive', 'type': 'gdrive', 'admitted': False}],
    }))
    (t / 'enabled.yaml').write_text(yaml.safe_dump({
        'schema': 'snowgloves.enabled.v1',
        'tenant': 'heyzack',
        'agents': [],
        'modules': [{'id': 'github-mcp', 'category': 'mcp'}],
    }))
    (t / 'MANIFEST.yaml').write_text(yaml.safe_dump({
        'tenant': 'heyzack',
        'brand': {'domain': 'FILL: confirm'},
    }))

    data = tmp_path / 'data'
    spec_dir = data / 'specs' / '006-editorial-steward-integration'
    spec_dir.mkdir(parents=True)
    (spec_dir / 'portfolio-map-proposal.json').write_text(json.dumps({
        'cross_brand_flows': [{
            'id': 'f1', 'status': 'proposed_not_approved',
            'participants': ['heyzack'], 'description': 'X',
        }],
    }))
    proposal = load_proposal(data)

    asks = derive_asks(tenants, 'heyzack', proposal)
    assert [a['kind'] for a in asks] == ['decision', 'connect', 'connect', 'website', 'brand']
    assert [a['role'] for a in asks] == ['chief-of-staff', 'dispatcher', 'dispatcher', 'interpreter', 'interpreter']
    assert [a['answer_type'] for a in asks] == ['yes_no', 'yes_no', 'yes_no', 'text', 'yes_no']
    assert all(a['proposed'] is None for a in asks)
    expected = [('decision', 'flow|f1'), ('connect', 'source|drive'), ('connect', 'module|github-mcp'),
                ('website', 'domain'), ('brand', 'meristem')]
    assert {a['id'] for a in asks} == {ask_id('heyzack', kind, key) for kind, key in expected}
    assert {a['source'] for a in asks} == {'portfolio-map-proposal.json', 'sources.yaml', 'enabled.yaml', 'MANIFEST.yaml'}
    assert asks[0]['title'] == 'X'

    (t / 'sources.yaml').write_text(yaml.safe_dump({
        'tenant': 'heyzack',
        'sources': [
            {'id': 'drive', 'type': 'gdrive', 'admitted': False},
            {'id': 'meristem-research', 'type': 'filesystem', 'admitted': True},
        ],
    }))
    asks = derive_asks(tenants, 'heyzack', proposal)
    assert not any(a['kind'] == 'brand' for a in asks)
    assert any(a['kind'] == 'connect' and a['source'] == 'sources.yaml' for a in asks)


def test_website_title_uses_fill_wording(tmp_path):
    t = tmp_path / 'heyzack'
    t.mkdir()
    manifest = t / 'MANIFEST.yaml'

    manifest.write_text(yaml.safe_dump({'tenant': 'heyzack', 'brand': {'domain': 'FILL: hey-zack.fr'}}))
    website = [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'website']
    assert [a['title'] for a in website] == ['hey-zack.fr']

    manifest.write_text(yaml.safe_dump({'tenant': 'heyzack', 'brand': {'domain': 'FILL:'}}))
    website = [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'website']
    assert [a['title'] for a in website] == ['Confirm brand domain']

    manifest.write_text(yaml.safe_dump({'tenant': 'heyzack', 'brand': {'domain': 'FILL: the api key for X'}}))
    assert [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'website'] == []

    manifest.write_text(yaml.safe_dump({'tenant': 'heyzack', 'brand': {'domain': 'FILL: ' + 'x' * 200}}))
    website = [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'website']
    assert len(website) == 1
    assert len(website[0]['title']) == 160


def test_sensitive_titles_dropped_and_caps(tmp_path):
    t = tmp_path / 'heyzack'
    (t / 'context').mkdir(parents=True)
    (t / 'context/a.md').write_text('FILL: the api key for X\n')
    (t / 'context/b.md').write_text('FILL: ' + 'x' * 200 + '\n')
    (t / 'context/c.md').write_text(''.join('FILL: question %d\n' % i for i in range(450)))
    asks = derive_asks(tmp_path, 'heyzack')
    assert len(asks) == 400
    assert all(a['kind'] == 'fact' for a in asks)
    assert all(len(a['title']) <= 160 for a in asks)
    assert all('api key' not in a['title'].lower() for a in asks)
    assert any(len(a['title']) == 160 for a in asks)


def test_broken_files_do_not_raise(tmp_path):
    t = tmp_path / 'heyzack'
    t.mkdir()
    (t / 'MANIFEST.yaml').write_text('tenant: [unclosed\n  bad: yaml')
    (t / 'sources.yaml').write_text('sources: [unclosed')
    (t / 'enabled.yaml').write_text('modules: [unclosed')
    assert derive_asks(tmp_path, 'heyzack') == []

    (t / 'context').mkdir()
    (t / 'context/ok.md').write_text('FILL: fine\n')
    (t / 'context/big.md').write_bytes(b'FILL: big\n' + b'x' * (256 * 1024))
    outside = tmp_path / 'outside.md'
    outside.write_text('FILL: linked\n')
    (t / 'context/linked.md').symlink_to(outside)
    assert [a['title'] for a in derive_asks(tmp_path, 'heyzack')] == ['fine']


def test_load_proposal_missing_invalid_and_oversize(tmp_path):
    assert load_proposal(tmp_path) is None
    spec_dir = tmp_path / 'specs' / '006-editorial-steward-integration'
    spec_dir.mkdir(parents=True)
    path = spec_dir / 'portfolio-map-proposal.json'
    path.write_text('{bad json')
    assert load_proposal(tmp_path) is None
    path.write_bytes(b'{"a": ' + b'1' * (512 * 1024) + b'}')
    assert load_proposal(tmp_path) is None
    path.write_text(json.dumps({'cross_brand_flows': []}))
    assert load_proposal(tmp_path) == {'cross_brand_flows': []}


def test_empty_proposal_keeps_fact_as_text(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True); (t / 'asks').mkdir()
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    ident = ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    (t / 'asks/proposed.jsonl').write_text(json.dumps({'ask_id': ident, 'proposed': '  '}) + '\n')
    ask = derive_asks(tmp_path, 'heyzack')[0]
    assert ask['answer_type'] == 'text' and ask['proposed'] is None


def test_duplicate_sources_yield_unique_ids(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\nFILL: the price.\n')
    (t / 'sources.yaml').write_text('tenant: heyzack\nsources:\n- {id: drive, type: gdrive, ingest: false}\n- {id: drive, type: gdrive, ingest: false}\n')
    asks = derive_asks(tmp_path, 'heyzack')
    ids = [a['id'] for a in asks]
    assert len(ids) == len(set(ids))
    assert [a['kind'] for a in asks].count('fact') == 1
    # The tenant view holds a source list with a repeated id, so it asks for no connection.
    assert [a['title'] for a in asks].count('Connect drive') == 0


def test_control_character_proposal_keeps_fact_as_text(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True); (t / 'asks').mkdir()
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    ident = ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    (t / 'asks/proposed.jsonl').write_text(json.dumps({'ask_id': ident, 'proposed': 'a\nb'}) + '\n')
    ask = derive_asks(tmp_path, 'heyzack')[0]
    assert ask['answer_type'] == 'text' and ask['proposed'] is None


def test_control_characters_in_titles_are_normalized(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('# Offer\nFILL: the\tprice.\n')
    proposal = {'cross_brand_flows': [{'id': 'f1', 'status': 'proposed_not_approved', 'participants': ['heyzack'],
                                       'description': 'line one\nline two'}]}
    asks = derive_asks(tmp_path, 'heyzack', proposal)
    assert asks and all(not re.search(r'[\x00-\x1f\x7f]', a['title'] + a['source']) for a in asks)
    titles = {a['kind']: a['title'] for a in asks}
    assert titles['fact'] == 'the price.'
    assert 'line one line two' in titles['decision']


def test_oversized_proposal_journal_keeps_the_newest_tail(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True); (t / 'asks').mkdir()
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    ident = ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    filler = json.dumps({'ask_id': 'f' * 32, 'proposed': 'x' * 400}) + '\n'
    with (t / 'asks/proposed.jsonl').open('w') as stream:
        stream.write(filler * 1000)
        stream.write(json.dumps({'ask_id': ident, 'proposed': 'EUR 99'}) + '\n')
    assert (t / 'asks/proposed.jsonl').stat().st_size > 256 * 1024
    ask = derive_asks(tmp_path, 'heyzack')[0]
    assert ask['answer_type'] == 'yes_no' and ask['proposed'] == 'EUR 99'


def test_sensitive_text_is_rechecked_after_normalization(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('# Offer\nFILL: the api\tkey for billing.\nFILL: the price.\n')
    (t / 'sources.yaml').write_text('tenant: heyzack\nsources:\n- {id: drive, type: gdrive, ingest: false}\n')
    titles = [a['title'] for a in derive_asks(tmp_path, 'heyzack')]
    assert 'the price.' in titles and 'Connect drive' in titles
    assert not any(SENSITIVE_RE.search(title) for title in titles)


def test_held_source_lists_ask_for_no_connection_or_brand_handoff(tmp_path):
    t = tmp_path / 'heyzack'; t.mkdir()
    held = [
        {'tenant': 'other', 'sources': [{'id': 'drive', 'type': 'gdrive', 'ingest': False}]},
        {'sources': [{'id': 'drive', 'type': 'gdrive', 'ingest': False}]},
        {'tenant': 'heyzack', 'sources': [{'id': 'drive', 'type': 'gdrive', 'tenant': 'other', 'ingest': False}]},
        {'tenant': 'heyzack', 'sources': [{'id': 'customer-token', 'type': 'gdrive', 'ingest': False},
                                          {'id': 'drive', 'type': 'gdrive', 'ingest': False}]},
        {'tenant': 'heyzack', 'sources': [{'id': 'drive', 'type': 'carrier-pigeon', 'ingest': False}]},
    ]
    for value in held:
        (t / 'sources.yaml').write_text(yaml.safe_dump(value))
        assert [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] in ('connect', 'brand')] == [], value


def test_long_context_filename_source_fits_the_client_limit(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context' / (('n' * 245) + '.md')).write_text('# Long\nFILL: the price.\n')
    asks = derive_asks(tmp_path, 'heyzack')
    facts = [a for a in asks if a['kind'] == 'fact']
    assert len(facts) == 1 and len(facts[0]['source']) <= 240


def test_symlinked_asks_directory_is_not_read(tmp_path):
    t = tmp_path / 'tenants' / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    ident = ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'proposed.jsonl').write_text(json.dumps({'ask_id': ident, 'proposed': 'EUR 1'}) + '\n')
    (t / 'asks').symlink_to(outside, target_is_directory=True)
    ask = derive_asks(tmp_path / 'tenants', 'heyzack')[0]
    assert ask['answer_type'] == 'text' and ask['proposed'] is None


def test_proposal_read_through_a_linked_directory_is_refused(tmp_path):
    data = tmp_path / 'data'; data.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'portfolio-map-proposal.json').write_text(json.dumps({'cross_brand_flows': []}))
    (data / 'specs').mkdir()
    (data / 'specs' / '006-editorial-steward-integration').symlink_to(outside, target_is_directory=True)
    assert load_proposal(data) is None


def test_module_connect_asks_use_catalog_categories(tmp_path):
    t = tmp_path / 'heyzack'; t.mkdir()
    (t / 'enabled.yaml').write_text(yaml.safe_dump({'schema': 'snowgloves.enabled.v1', 'tenant': 'heyzack', 'agents': [], 'modules': [
        'github-mcp', {'id': 'stale', 'category': 'mcp'}, {'id': 'gmail', 'category': 'skills'}]}))
    catalog = {'github-mcp': 'mcp', 'stale': 'skills', 'gmail': 'connector'}
    titles = sorted(a['title'] for a in derive_asks(tmp_path, 'heyzack', catalog=catalog) if a['kind'] == 'connect')
    assert titles == ['Connect github-mcp', 'Connect gmail']


def test_held_enablement_asks_for_no_connector(tmp_path):
    t = tmp_path / 'heyzack'; t.mkdir()
    catalog = {'github-mcp': 'mcp', 'gmail': 'connector'}
    held = [
        {'schema': 'snowgloves.enabled.v1', 'tenant': 'other', 'agents': [], 'modules': ['github-mcp']},
        {'schema': 'wrong', 'tenant': 'heyzack', 'agents': [], 'modules': ['github-mcp']},
        {'schema': 'snowgloves.enabled.v1', 'tenant': 'heyzack', 'agents': [], 'modules': ['github-mcp', 'github-mcp']},
        {'schema': 'snowgloves.enabled.v1', 'tenant': 'heyzack', 'agents': [], 'modules': ['github-mcp', {'id': 'Bad ID'}]},
        {'schema': 'snowgloves.enabled.v1', 'tenant': 'heyzack', 'agents': ['librarian', 'librarian'], 'modules': ['gmail']},
        {'schema': 'snowgloves.enabled.v1', 'tenant': 'heyzack', 'modules': ['gmail']},
    ]
    for value in held:
        (t / 'enabled.yaml').write_text(yaml.safe_dump(value))
        assert [a for a in derive_asks(tmp_path, 'heyzack', catalog=catalog) if a['kind'] == 'connect'] == [], value


def test_load_catalog_maps_ids_to_categories(tmp_path):
    (tmp_path / 'catalog').mkdir()
    ok = {'disposition': 'add', 'enableable': True, 'risk': 'low', 'approval': 'no', 'agents': ['librarian']}
    catalog = {'schema': 'snowgloves.modules.v1', 'agents': [{'slug': 'librarian', 'role': 'Librarian'}], 'cards': [
        {'id': 'github-mcp', 'category': 'mcp', **ok}, {'id': 'x', 'category': 'skills', **ok, 'disposition': 'pointer'},
        {'id': 'lazyweb', 'category': 'mcp', **ok, 'disposition': 'hold', 'enableable': False},
        {'id': 'awesome', 'category': 'mcp', **ok, 'disposition': 'refuse'},
        {'id': 'draft', 'category': 'connector', **ok, 'enableable': None},
        {'id': 'no-risk', 'category': 'mcp', **{k: v for k, v in ok.items() if k != 'risk'}},
        {'id': 'no-approval', 'category': 'mcp', **ok, 'approval': 'maybe'},
        {'id': 'stranger', 'category': 'connector', **ok, 'agents': ['ghost']},
        {'nope': 1}]}
    (tmp_path / 'catalog' / 'modules.json').write_text(json.dumps(catalog))
    # Every card the tenant view gates as held stays out of connector asks.
    assert load_catalog(tmp_path) == {'github-mcp': 'mcp', 'x': 'skills'}
    assert load_catalog(tmp_path / 'missing') == {}
    # A catalog the tenant view holds (wrong schema, or over its 1 MiB limit) asks for nothing.
    (tmp_path / 'catalog' / 'modules.json').write_text(json.dumps({**catalog, 'schema': 'other'}))
    assert load_catalog(tmp_path) == {}
    (tmp_path / 'catalog' / 'modules.json').write_text(json.dumps({**catalog, 'padding': 'x' * (1024 * 1024)}))
    assert load_catalog(tmp_path) == {}


def test_a_manifest_naming_another_tenant_asks_for_no_website(tmp_path):
    t = tmp_path / 'heyzack'; t.mkdir()
    for value, expected in (({'tenant': 'heyzack', 'brand': {'domain': 'FILL: confirm'}}, 1),
                            ({'tenant': 'other', 'brand': {'domain': 'FILL: confirm'}}, 0),
                            ({'brand': {'domain': 'FILL: confirm'}}, 0)):
        (t / 'MANIFEST.yaml').write_text(yaml.safe_dump(value))
        assert len([a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'website']) == expected, value


def test_fact_derivation_stops_at_the_cap(tmp_path, monkeypatch):
    import lib.tenant_asks as ta
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    for i in range(30):
        (t / 'context' / ('f%02d.md' % i)).write_text(''.join('FILL: item %d-%d\n' % (i, j) for j in range(20)))
    reads = []
    original = ta._read_text
    monkeypatch.setattr(ta, '_read_text', lambda path: (reads.append(path), original(path))[1])
    asks = derive_asks(tmp_path, 'heyzack')
    assert len([a for a in asks if a['kind'] == 'fact']) == 400
    assert len(reads) == 20


def test_proposals_with_lone_surrogates_are_ignored(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True); (t / 'asks').mkdir()
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    ident = ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    (t / 'asks/proposed.jsonl').write_text('{"ask_id": "%s", "proposed": "bad \\ud800"}\n' % ident)
    ask = derive_asks(tmp_path, 'heyzack')[0]
    assert ask['answer_type'] == 'text' and ask['proposed'] is None


def test_decision_titles_with_lone_surrogates_are_dropped(tmp_path):
    (tmp_path / 'heyzack').mkdir()
    proposal = {'cross_brand_flows': [
        {'id': 'bad', 'status': 'proposed_not_approved', 'participants': ['heyzack'], 'description': 'bad \ud800 flow'},
        {'id': 'good', 'status': 'proposed_not_approved', 'participants': ['heyzack'], 'description': 'good flow'}]}
    titles = [a['title'] for a in derive_asks(tmp_path, 'heyzack', proposal) if a['kind'] == 'decision']
    assert len(titles) == 1 and 'good flow' in titles[0]


def test_fill_lines_cannot_starve_other_asks(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context' / 'big.md').write_text(''.join('FILL: item %d\n' % i for i in range(450)))
    (t / 'sources.yaml').write_text(yaml.safe_dump({
        'tenant': 'heyzack', 'sources': [{'id': 'drive', 'type': 'gdrive', 'admitted': False}]}))
    (t / 'MANIFEST.yaml').write_text(yaml.safe_dump({'tenant': 'heyzack', 'brand': {'domain': 'FILL: confirm'}}))
    proposal = {'cross_brand_flows': [{'id': 'f1', 'status': 'proposed_not_approved', 'participants': ['heyzack'],
                                       'description': 'share leads'}]}
    asks = derive_asks(tmp_path, 'heyzack', proposal)
    kinds = [a['kind'] for a in asks]
    assert len(asks) == 400
    # Decisions lead, then connection, website and brand asks, then the facts.
    assert kinds[0] == 'decision' and kinds[1:4] == ['connect', 'website', 'brand'] and set(kinds[4:]) == {'fact'}
    assert 'decision' in kinds and 'connect' in kinds and 'website' in kinds and 'brand' in kinds
    assert kinds.count('fact') == 400 - (len(asks) - kinds.count('fact'))


def test_a_proposal_far_behind_the_journal_end_still_counts(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'asks').mkdir(parents=True)
    filler = json.dumps({'ask_id': 'f' * 32, 'proposed': 'x' * 400}) + '\n'
    (t / 'asks' / 'proposed.jsonl').write_text(
        json.dumps({'ask_id': 'a' * 32, 'proposed': 'EUR 99'}) + '\n' + filler * 2000
        + '{"ask_id": "' + 'b' * 32 + '", "proposed": "' + 'y' * 70000 + '"}\n'
        + json.dumps({'ask_id': 'c' * 32, 'proposed': 'yes'}) + '\n')
    assert (t / 'asks' / 'proposed.jsonl').stat().st_size > 256 * 1024
    proposals = load_proposals(t)
    # The early record survives, an oversized line is skipped whole, and the next line still parses.
    assert proposals['a' * 32] == 'EUR 99' and proposals['c' * 32] == 'yes' and 'b' * 32 not in proposals


def test_journal_history_never_crowds_out_a_current_asks_proposal(tmp_path):
    from lib.tenant_asks import MAX_PROPOSAL_IDS
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True); (t / 'asks').mkdir()
    (t / 'context' / 'offer.md').write_text('# Offer\nFILL: the price.\n')
    target = ask_id('heyzack', 'fact', 'context/offer.md|the price.')
    history = ''.join(json.dumps({'ask_id': '%032x' % n, 'proposed': 'old'}) + '\n' for n in range(MAX_PROPOSAL_IDS + 50))
    (t / 'asks' / 'proposed.jsonl').write_text(history + json.dumps({'ask_id': target, 'proposed': 'EUR 99'}) + '\n')
    ask = [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'fact'][0]
    assert ask['answer_type'] == 'yes_no' and ask['proposed'] == 'EUR 99'
    # Without a wanted set the newest ids win, so a new ask is never locked out.
    loaded = load_proposals(t)
    assert len(loaded) == MAX_PROPOSAL_IDS and loaded[target] == 'EUR 99' and '%032x' % 0 not in loaded


def test_a_huge_portfolio_proposal_cannot_crowd_out_connection_and_brand_asks(tmp_path):
    from lib.tenant_asks import MAX_ASKS
    t = tmp_path / 'heyzack'; t.mkdir()
    (t / 'sources.yaml').write_text(yaml.safe_dump({'tenant': 'heyzack', 'sources': [{'id': 'drive', 'type': 'gdrive', 'ingest': False}]}))
    (t / 'MANIFEST.yaml').write_text(yaml.safe_dump({'tenant': 'heyzack', 'brand': {'domain': 'FILL: confirm the domain'}}))
    proposal = {'cross_brand_flows': [{'id': 'flow-%d' % n, 'participants': ['heyzack', 'sunfeed'], 'status': 'proposed',
                                       'description': 'Flow %d' % n} for n in range(MAX_ASKS + 50)]}
    asks = derive_asks(tmp_path, 'heyzack', proposal)
    kinds = [a['kind'] for a in asks]
    assert len(asks) == MAX_ASKS
    assert {'connect', 'website', 'brand'} <= set(kinds) and kinds.count('decision') == MAX_ASKS - 3
    # Decisions still lead the list.
    assert kinds[0] == 'decision' and kinds[-3:] == ['connect', 'website', 'brand']


def test_a_context_file_swapped_for_a_link_is_never_read(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    other = tmp_path / 'other'; (other / 'context').mkdir(parents=True)
    (other / 'context' / 'offer.md').write_text('# Offer\nFILL: other tenant secret plan.\n')
    (t / 'context' / 'offer.md').symlink_to(other / 'context' / 'offer.md')
    (t / 'context' / 'own.md').write_text('# Own\nFILL: the price.\n')
    titles = [a['title'] for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'fact']
    assert titles == ['the price.']
    # A linked context directory is not followed either.
    import shutil
    shutil.rmtree(t / 'context')
    (t / 'context').symlink_to(other / 'context', target_is_directory=True)
    assert [a for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'fact'] == []


def test_a_proposal_file_swapped_for_a_link_is_never_read(tmp_path):
    data = tmp_path / 'data'
    spec = data / 'specs' / '006-editorial-steward-integration'
    spec.mkdir(parents=True)
    outside = tmp_path / 'private.json'
    outside.write_text(json.dumps({'cross_brand_flows': [{'id': 'leak'}]}))
    (spec / 'portfolio-map-proposal.json').symlink_to(outside)
    assert load_proposal(data) is None
    (spec / 'portfolio-map-proposal.json').unlink()
    (spec / 'portfolio-map-proposal.json').write_text(json.dumps({'cross_brand_flows': []}))
    assert load_proposal(data) == {'cross_brand_flows': []}


def test_proposal_scan_stops_at_its_total_budget(tmp_path, monkeypatch):
    import lib.tenant_asks as ta
    t = tmp_path / 'heyzack'; (t / 'asks').mkdir(parents=True)
    rows = ''.join(json.dumps({'ask_id': '%032x' % n, 'proposed': 'p%d' % n}) + '\n' for n in range(100))
    (t / 'asks' / 'proposed.jsonl').write_text(rows)
    monkeypatch.setattr(ta, 'MAX_PROPOSAL_SCAN_BYTES', 1000)
    loaded = load_proposals(t)
    assert 0 < len(loaded) < 100


def test_journal_scan_budget_also_covers_an_oversized_line(tmp_path, monkeypatch):
    import lib.tenant_asks as ta
    t = tmp_path / 'heyzack'; (t / 'asks').mkdir(parents=True)
    (t / 'asks' / 'proposed.jsonl').write_text('{"ask_id": "' + 'x' * 500000 + '\n'
                                              + json.dumps({'ask_id': 'a' * 32, 'proposed': 'late'}) + '\n')
    monkeypatch.setattr(ta, 'MAX_PROPOSAL_SCAN_BYTES', 200000)
    # The skip of the long line stops at the budget instead of reading the whole line.
    assert load_proposals(t) == {}


def test_repeated_fill_lines_do_not_spend_the_fact_budget(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context' / 'a.md').write_text('FILL: the price.\n' * 500 + 'FILL: the offer window.\n')
    (t / 'context' / 'b.md').write_text('FILL: the launch date.\n')
    titles = [a['title'] for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'fact']
    assert titles == ['the price.', 'the offer window.', 'the launch date.']


def test_context_scan_stops_at_its_byte_budget(tmp_path, monkeypatch):
    import lib.tenant_asks as ta
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    for n in range(5):
        (t / 'context' / ('%02d.md' % n)).write_text('# notes\n' + 'x' * 1000 + '\nFILL: question %d.\n' % n)
    monkeypatch.setattr(ta, 'MAX_CONTEXT_BYTES', 2500)
    titles = [a['title'] for a in derive_asks(tmp_path, 'heyzack') if a['kind'] == 'fact']
    # Files are read in order until the shared budget is spent; the rest wait.
    assert titles == ['question 0.', 'question 1.', 'question 2.']
