"""Tenant map must never turn source declarations into runtime authority."""
import json
from pathlib import Path

import pytest
import yaml

from lib.cockpit_tenant_map import MAX_BYTES, capability_map
from lib.cockpit_snapshot import build_snapshot


@pytest.fixture
def tree(tmp_path):
    repo = tmp_path / 'repo'
    tenant = tmp_path / 'data' / 'tenants' / 'acme'
    tenant.mkdir(parents=True)
    (repo / 'catalog').mkdir(parents=True)
    catalog = {
        'schema': 'snowgloves.modules.v1',
        'agents': [{'slug': 'cto', 'role': 'Technology'}, {'slug': 'sentinel', 'role': 'Audit'}],
        'adapters': [{'id': 'codex'}],
        'cards': [
            {'id': ident, 'name': ident, 'category': category, 'disposition': disposition,
             'risk': 'high', 'approval': 'yes', 'agents': ['cto'], 'enableable': True}
            for ident, category, disposition in [('skill-a', 'skills', 'add'), ('connector-a', 'connector', 'pointer'), ('held-a', 'plugin', 'hold'), ('refused-a', 'mcp', 'refuse')]]
    }
    (repo / 'catalog' / 'modules.json').write_text(json.dumps(catalog))
    (repo / 'catalog' / 'business-roles.json').write_text(json.dumps([{'id': 'writer', 'name': 'Writer', 'desk': 'editorial', 'control_owner': 'cto', 'preparation_only': True}]))
    (tenant / 'enabled.yaml').write_text(yaml.safe_dump({'schema': 'snowgloves.enabled.v1', 'tenant': 'acme', 'agents': ['cto'], 'modules': [{'id': 'skill-a', 'risk': 'low', 'approval': 'no'}, 'connector-a', 'held-a', 'refused-a', 'unknown-a']}))
    (tenant / 'runtime.yaml').write_text(yaml.safe_dump({'schema': 'snowgloves.runtime.v1', 'tenant': 'acme', 'primary': 'codex'}))
    (tenant / 'sources.yaml').write_text(yaml.safe_dump({'tenant': 'acme', 'sources': [{'id': 'brand-docs', 'type': 'filesystem', 'path': '/private/SECRET_PATH', 'note': 'SECRET_NOTE', 'ingest': True}]}))
    return repo, tenant


def test_catalog_authority_and_available_vs_assigned(tree):
    result = capability_map(*tree)
    modules = {m['id']: m for m in result['configuredModules']}
    assert modules['skill-a']['risk'] == 'high'
    assert modules['skill-a']['approval'] == 'yes'
    assert modules['skill-a']['gate'] == 'approval_required'
    assert modules['skill-a']['roles'] == ['cto']
    assert [modules[m]['gate'] for m in ['held-a', 'refused-a', 'unknown-a']] == ['held'] * 3
    assert result['assignedAgents'] == [{'id': 'cto', 'status': 'configured'}]
    assert len(result['availableControlRoles']) == 2
    assert result['availableBusinessRoles'][0]['preparationOnly'] is True
    assert result['connectionAuth'] == 'unverified'
    assert result['status'] == 'source_config_only'
    assert result['registeredSources'] == [{'id': 'brand-docs', 'type': 'filesystem', 'admitted': True}]
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('risk,approval,gate', [('high', 'no', 'approval_required'), ('high', 'yes', 'approval_required'), ('low', 'yes', 'approval_required'), ('low', 'no', 'catalog_permitted'), ('medium', 'no', 'catalog_permitted')])
def test_approval_gate_includes_independent_high_risk_rule(tree, risk, approval, gate):
    repo, tenant = tree
    path = repo / 'catalog' / 'modules.json'
    catalog = json.loads(path.read_text())
    catalog['cards'][0].update(risk=risk, approval=approval)
    path.write_text(json.dumps(catalog))
    module = capability_map(repo, tenant)['configuredModules'][0]
    assert module['risk'] == risk
    assert module['approval'] == approval
    assert module['gate'] == gate


@pytest.mark.parametrize('file,field,schema', [('enabled.yaml', 'enabledState', 'snowgloves.enabled.v1'), ('runtime.yaml', 'runtimeState', 'snowgloves.runtime.v1'), ('sources.yaml', 'sourcesState', None)])
def test_foreign_tenant_held(tree, file, field, schema):
    repo, tenant = tree
    data = yaml.safe_load((tenant / file).read_text())
    data['tenant'] = 'other'
    (tenant / file).write_text(yaml.safe_dump(data))
    result = capability_map(repo, tenant)
    assert result[field] == 'held'
    if field == 'enabledState':
        assert result['configuredModules'] == result['assignedAgents'] == []
    elif field == 'runtimeState':
        assert result['runtime'] is None
    else:
        assert result['registeredSources'] == []


@pytest.mark.parametrize('mode', ['symlink', 'oversize', 'malformed', 'alias', 'duplicate', 'unhashable', 'wrong-schema', 'wrong-modules'])
def test_unsafe_enabled_held(tree, mode):
    repo, tenant = tree
    path = tenant / 'enabled.yaml'
    content = path.read_text()
    if mode == 'symlink':
        target = tenant.parent / 'outside.yaml'
        target.write_text(content)
        path.unlink()
        path.symlink_to(target)
    else:
        path.write_text({'oversize': 'x' * (MAX_BYTES + 1), 'malformed': '[bad', 'alias': 'a: &x []\nb: *x', 'duplicate': content + '\ntenant: acme\n', 'unhashable': '? [a, b]\n: 1', 'wrong-schema': content.replace('snowgloves.enabled.v1', 'snowgloves.enabled.v9'), 'wrong-modules': 'schema: snowgloves.enabled.v1\ntenant: acme\nmodules: {}\nagents: []'}[mode])
    result = capability_map(repo, tenant)
    assert result['enabledState'] == 'held'
    assert result['configuredModules'] == result['assignedAgents'] == []


def test_missing_and_ancestor_symlink_fail_closed(tree):
    repo, tenant = tree
    (tenant / 'enabled.yaml').unlink()
    (tenant / 'runtime.yaml').unlink()
    result = capability_map(repo, tenant)
    assert result['enabledState'] == result['runtimeState'] == 'missing'
    alias = tenant.parent / 'alias'
    alias.symlink_to(tenant, target_is_directory=True)
    assert capability_map(repo, alias)['sourcesState'] == 'held'


def test_unsafe_identifiers_and_source_text_not_exposed(tree):
    repo, tenant = tree
    (tenant / 'enabled.yaml').write_text(yaml.safe_dump({'schema': 'snowgloves.enabled.v1', 'tenant': 'acme', 'agents': ['../../outside', 'token-123', 'cto', 'unregistered'], 'modules': ['secret-123', 'https://private', '<img src=x>', {'id': 'skill-a', 'name': 'TOKEN_VALUE'}]}))
    (tenant / 'sources.yaml').write_text(yaml.safe_dump({'tenant': 'acme', 'sources': [{'id': 'ok', 'type': 'filesystem', 'ingest': False, 'url': 'https://private'}, {'id': 'foreign', 'type': 'filesystem', 'tenant': 'other', 'ingest': True}, {'id': 'token-123', 'type': 'filesystem'}, {'id': 'bad-type', 'type': ['filesystem']}, {'id': 'bad-admission', 'type': 'filesystem', 'ingest': 'yes'}]}))
    result = capability_map(repo, tenant)
    assert [m['id'] for m in result['configuredModules']] == ['skill-a']
    assert result['assignedAgents'] == [{'id': 'cto', 'status': 'configured'}, {'id': 'unregistered', 'status': 'held'}]
    assert result['registeredSources'] == [{'id': 'ok', 'type': 'filesystem', 'admitted': False}]
    for excluded in ['TOKEN_VALUE', 'token-123', 'https://private', 'foreign', '<img']:
        assert excluded not in json.dumps(result)


@pytest.mark.parametrize('mode', ['duplicate-card', 'symlink', 'schema', 'bad-agent'])
def test_catalog_failure_cannot_make_config_usable(tree, mode):
    repo, tenant = tree
    path = repo / 'catalog' / 'modules.json'
    catalog = json.loads(path.read_text())
    if mode == 'duplicate-card':
        catalog['cards'].append(catalog['cards'][0])
    elif mode == 'schema':
        catalog['schema'] = 'wrong'
    elif mode == 'bad-agent':
        catalog['cards'][0]['agents'] = [None]
    if mode == 'symlink':
        copy = path.with_suffix('.copy')
        copy.write_text(json.dumps(catalog))
        path.unlink()
        path.symlink_to(copy)
    else:
        path.write_text(json.dumps(catalog))
    result = capability_map(repo, tenant)
    assert result['configuredModules'][0]['gate'] == 'held'
    if mode in ['symlink', 'schema']:
        assert result['catalogState'] == 'held'
        assert result['runtimeState'] == 'held'


def test_snapshot_integration_read_only_and_public_catalog_counts(tree):
    repo, tenant = tree
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for root in tree for p in root.rglob('*') if p.is_file()}
    snapshot = build_snapshot(repo, data_root=tenant.parents[1], probe=False)
    assert snapshot['tenants'][0]['capabilityMap'] == capability_map(repo, tenant)
    assert all((p.stat().st_size, p.stat().st_mtime_ns) == stat for p, stat in before.items())
    public_repo = Path(__file__).resolve().parents[1]
    result = capability_map(public_repo, tenant)
    assert len(result['availableControlRoles']) == 7
    assert len(result['availableBusinessRoles']) == 19
    assert result['assignedAgents'] == [{'id': 'cto', 'status': 'configured'}]
