import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('source_audit', Path(__file__).resolve().parents[1] / 'scripts/fleet/source_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def root(tmp_path):
    tenant = tmp_path / 'tenants/alpha'
    (tenant / 'context').mkdir(parents=True)
    (tenant / 'context/voice.md').write_text('Reviewed voice\n')
    (tenant / 'sources.yaml').write_text('tenant: alpha\nsources:\n- id: context\n  type: filesystem\n  path: tenants/alpha/context\n  ingest: true\n  include_glob: ["**/*.md"]\n')
    return tmp_path


def policy(root):
    path = root / 'held.json'
    path.write_text('{"private": "synthetic-secret-not-for-transfer"}')
    value = {'schema': 'snowgloves.controller-data-policy.v1', 'excluded_paths': ['held.json'],
             'dispositions': [{'path': 'held.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                               'disposition': 'held-private', 'transfer': False, 'ingest': False,
                               'reason': 'Retain privately until separate clearance'}]}
    target = root / 'policy.json'
    target.write_text(json.dumps(value))
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def test_actual_tenant_files_are_hashed_without_mutating_tree(root):
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = audit.tenant_audit(root)
    assert result['tenants'] == 1 and result['unexpected_holds'] == []
    assert result['sources'][0]['files'][0]['sha256'] == hashlib.sha256(b'Reviewed voice\n').hexdigest()
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode', ['cross-tenant', 'symlink', 'missing'])
def test_unsafe_or_missing_sources_are_held_without_reading_foreign_data(root, mode):
    source = root / 'tenants/alpha/sources.yaml'
    if mode == 'cross-tenant':
        source.write_text(source.read_text().replace('tenants/alpha/context', 'tenants/beta/context'))
        (root / 'tenants/beta/context').mkdir(parents=True)
        (root / 'tenants/beta/context/secret.md').write_text('foreign-secret')
    elif mode == 'symlink':
        (root / 'outside.md').write_text('foreign-secret')
        (root / 'tenants/alpha/context/link.md').symlink_to(root / 'outside.md')
    else:
        (root / 'tenants/alpha/context/voice.md').unlink()
        (root / 'tenants/alpha/context').rmdir()
    result = audit.tenant_audit(root)
    assert result['unexpected_holds'] and result['sources'][0]['files'] == []
    assert 'foreign-secret' not in json.dumps(result)


def test_external_host_reference_is_explicitly_excluded(root):
    source = root / 'tenants/alpha/sources.yaml'
    source.write_text(source.read_text()+'- id: capability\n  type: filesystem\n  path: /missing/host/skill\n  ingest: false\n')
    result = audit.tenant_audit(root)
    assert result['unexpected_holds'] == []
    assert result['sources'][1]['status'] == 'held' and result['sources'][1]['present'] is False


@pytest.mark.parametrize('mode', ['declared', 'copy', 'symlink', 'hardlink'])
def test_transfer_gate_rejects_held_bytes_and_aliases(root, mode):
    path, checksum = policy(root)
    candidate = root / 'alias.json'
    if mode == 'declared':
        name = 'held.json'
    elif mode == 'copy':
        candidate.write_bytes((root / 'held.json').read_bytes()); name = candidate.name
    elif mode == 'symlink':
        candidate.symlink_to(root / 'held.json'); name = candidate.name
    else:
        candidate.hardlink_to(root / 'held.json'); name = candidate.name
    result = audit.disposition_audit(root, path, checksum, [name])
    assert result['rejected_candidates'] == [name] and result['transfer_allowed'] is False
    assert 'synthetic-secret' not in json.dumps(result)


def test_changed_policy_or_held_file_requires_new_disposition(root):
    path, checksum = policy(root)
    with pytest.raises(ValueError, match='checksum'):
        audit.disposition_audit(root, path, '0' * 64)
    (root / 'held.json').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        audit.disposition_audit(root, path, checksum)


def test_duplicate_yaml_cannot_widen_source_scope(root):
    source = root / 'tenants/alpha/sources.yaml'
    source.write_text(source.read_text()+'tenant: beta\n')
    with pytest.raises(ValueError, match='duplicate'):
        audit.tenant_audit(root)


def test_cli_reports_safe_failure_and_requires_bound_policy(root, capsys):
    path, checksum = policy(root)
    assert audit.main(['--data-root', str(root), '--policy', str(path)]) == 3
    assert audit.main(['--data-root', str(root), '--policy', str(path), '--policy-digest', checksum]) == 0
    assert 'synthetic-secret' not in capsys.readouterr().out


@pytest.mark.parametrize('value', [[], None, 'synthetic-secret'])
def test_cli_rejects_non_object_policy_without_echoing_input(root, capsys, value):
    path = root / 'invalid-policy.json'
    path.write_text(json.dumps(value))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    assert audit.main(['--data-root', str(root), '--policy', str(path), '--policy-digest', checksum]) == 3
    output = json.loads(capsys.readouterr().out)
    assert output['passed'] is False
    assert 'synthetic-secret' not in json.dumps(output)
