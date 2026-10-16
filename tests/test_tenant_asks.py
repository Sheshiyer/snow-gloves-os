"""Founder asks derived from tenant files: bounded, sensitive-safe, never raising."""
import json
import re
from pathlib import Path

import yaml

from lib.tenant_asks import SENSITIVE_RE, ASK_KINDS, ROLE_FOR_KIND, ask_id, derive_asks, load_proposal


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
    (t / 'sources.yaml').write_text('sources:\n- {id: drive, type: gdrive, ingest: false}\n- {id: drive, type: gdrive, ingest: false}\n')
    asks = derive_asks(tmp_path, 'heyzack')
    ids = [a['id'] for a in asks]
    assert len(ids) == len(set(ids))
    assert [a['kind'] for a in asks].count('fact') == 1
    assert [a['title'] for a in asks].count('Connect drive') == 1


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
    (t / 'sources.yaml').write_text('sources:\n- {id: customer-token, type: gdrive, ingest: false}\n- {id: drive, type: gdrive, ingest: false}\n')
    titles = [a['title'] for a in derive_asks(tmp_path, 'heyzack')]
    assert 'the price.' in titles and 'Connect drive' in titles
    assert not any(SENSITIVE_RE.search(title) for title in titles)


def test_long_context_filename_source_fits_the_client_limit(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context' / (('n' * 245) + '.md')).write_text('# Long\nFILL: the price.\n')
    asks = derive_asks(tmp_path, 'heyzack')
    facts = [a for a in asks if a['kind'] == 'fact']
    assert len(facts) == 1 and len(facts[0]['source']) <= 240
