"""Private owner context stays bounded, tenant-bound, and non-authorizing."""
import json

import pytest

from lib.cockpit_brand_summary import MAX_JSON_BYTES, brand_summary
from lib.cockpit_snapshot import build_snapshot


def row(tenant='alpha'):
    return {'tenant': tenant, 'displayName': 'Current Brand', 'status': 'owner_confirmed', 'planningReview': 'pending', 'issues': ['legacy_slug', 'parent_unconfirmed'], 'sourceIds': ['company-context']}


@pytest.fixture
def reconciliation_tree(tmp_path):
    root = tmp_path / 'data'
    tenant = root / 'tenants' / 'alpha'
    tenant.mkdir(parents=True)
    (root / 'tenants' / 'beta').mkdir()
    path = root / 'specs' / '006-editorial-steward-integration' / 'tenant-reconciliation.json'
    path.parent.mkdir(parents=True)
    packet = {'schema': 'snowgloves.tenant-reconciliation.v1', 'authority': 'context_only', 'tenants': [row()]}
    path.write_text(json.dumps(packet))
    return root, tenant, path, packet


def test_reconciliation_projects_only_matching_tenant_and_preserves_source_files(reconciliation_tree):
    root, tenant, path, packet = reconciliation_tree
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert brand_summary(root, tenant, None)['reconciliation'] == row()
    assert 'reconciliation' not in brand_summary(root, root / 'tenants' / 'beta', None)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert set(brand_summary(root, tenant, None)['reconciliation']) == set(row())


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(schema='wrong'),
    lambda p: p.update(authority='runtime_authorized'),
    lambda p: p.update(notes='PRIVATE_NOTES'),
    lambda p: p.update(tenants={}),
    lambda p: p.update(tenants=[row()] * 129),
    lambda p: p['tenants'].append(row()),
    lambda p: p['tenants'][0].update(notes='PRIVATE_NOTES'),
    lambda p: p['tenants'][0].update(enabled=True),
    lambda p: p['tenants'][0].update(displayName='<script>bad</script>'),
    lambda p: p['tenants'][0].update(displayName='password private'),
    lambda p: p['tenants'][0].update(displayName='https://private'),
    lambda p: p['tenants'][0].update(displayName='X' * 65),
    lambda p: p['tenants'][0].update(status='active'),
    lambda p: p['tenants'][0].update(planningReview='approved_for_execution'),
    lambda p: p['tenants'][0].update(issues=['free text']),
    lambda p: p['tenants'][0].update(issues=['legacy_slug', 'legacy_slug']),
    lambda p: p['tenants'][0].update(sourceIds=['/private/notes']),
    lambda p: p['tenants'][0].update(sourceIds=['token-private']),
    lambda p: p['tenants'][0].update(sourceIds=['company-context'] * 17),
    lambda p: p['tenants'][0].update(sourceIds=[]),
    lambda p: p['tenants'][0].pop('planningReview'),
])
def test_invalid_packet_never_grants_or_projects_partial_context(reconciliation_tree, mutation):
    root, tenant, path, packet = reconciliation_tree
    mutation(packet)
    path.write_text(json.dumps(packet))
    result = brand_summary(root, tenant, None)
    assert 'reconciliation' not in result
    assert 'PRIVATE_NOTES' not in json.dumps(result)


@pytest.mark.parametrize('failure', ['file-symlink', 'directory-symlink', 'oversize', 'malformed', 'duplicate-key'])
def test_reconciliation_reader_fails_closed(reconciliation_tree, failure):
    root, tenant, path, packet = reconciliation_tree
    if failure == 'file-symlink':
        copy = path.with_suffix('.copy')
        path.rename(copy)
        path.symlink_to(copy)
    elif failure == 'directory-symlink':
        directory = path.parent
        copy = directory.with_name('outside')
        directory.rename(copy)
        directory.symlink_to(copy, target_is_directory=True)
    elif failure == 'oversize':
        path.write_text(json.dumps(packet) + ' ' * MAX_JSON_BYTES)
    elif failure == 'duplicate-key':
        path.write_text(json.dumps(packet)[:-1] + ',"authority":"context_only"}')
    else:
        path.write_text('{')
    assert 'reconciliation' not in brand_summary(root, tenant, None)


def test_snapshot_reconciliation_is_explicitly_private_and_tenant_scoped(reconciliation_tree, monkeypatch):
    root, tenant, path, packet = reconciliation_tree
    monkeypatch.setenv('SNOWGLOVES_DATA', str(root))
    # The same root deliberately contains the packet, proving public mode never reads it.
    public = build_snapshot(root, probe=False)
    assert all('reconciliation' not in t for t in public['tenants'])
    private = build_snapshot(root, data_root=root, tenant='alpha', probe=False)
    assert private['tenants'][0]['slug'] == 'alpha'
    assert private['tenants'][0]['reconciliation'] == row()
    other = build_snapshot(root, data_root=root, tenant='beta', probe=False)
    assert 'reconciliation' not in other['tenants'][0]
    assert private['capabilities']['execute'] is False
    assert private['capabilities']['enable'] is False
