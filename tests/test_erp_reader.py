"""The live ERP reader enforces the reference contract in code: admitted contract only, one read tool, SELECT-only,
bounded rows, identifiers from a verified binding, ids only."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.erp_reader import ErpGateError, ErpQueryError, ErpReader, validate_query, verify_links
from lib.tenant_vault import Vault

ADMITTED = {'status': 'admitted', 'mutation_tools_enabled': False, 'max_rows': 100, 'read_tool': 'execute_read_only_query',
            'excluded_tool': {'name': 'record_count'}, 'private_customer_records_approved': False}
BINDING = {'table': 'clients', 'id_column': 'id', 'verified_revision': 'schema-2026-10-10'}


class FakeErp:
    def __init__(self, existing=(), truncated=False, success=True):
        self.calls, self.existing, self.truncated, self.success = [], set(existing), truncated, success

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        if not self.success:
            return {'success': False, 'error': 'boom', 'columns': [], 'rows': [], 'row_count': 0, 'truncated': False}
        listed = __import__('re').search(r'IN \(([^)]*)\)', arguments['query'])
        ids = [int(x) for x in listed.group(1).split(',') if x.strip()] if listed else []
        rows = [[i] for i in ids if i in self.existing]
        return {'success': True, 'columns': ['id'], 'rows': rows, 'row_count': len(rows), 'truncated': self.truncated, 'error': None}


def reader(call=None, contract=None, binding=BINDING):
    return ErpReader(call or FakeErp(), contract or ADMITTED, binding)


# --- the gate -----------------------------------------------------------------------------------------------------
def test_a_contract_that_is_not_admitted_blocks_every_read():
    located = dict(ADMITTED, status='reference_contract_located_not_admitted')
    erp = FakeErp()
    with pytest.raises(ErpGateError) as exc:
        ErpReader(erp, located, BINDING).existing_ids([1])
    assert 'not admitted' in str(exc.value) and erp.calls == []


def test_mutation_tools_enabled_blocks_reads():
    with pytest.raises(ErpGateError):
        ErpReader(FakeErp(), dict(ADMITTED, mutation_tools_enabled=True), BINDING).existing_ids([1])
    with pytest.raises(ErpGateError):
        ErpReader(FakeErp(), {k: v for k, v in ADMITTED.items() if k != 'mutation_tools_enabled'}, BINDING).existing_ids([1])


def test_a_binding_without_a_verified_schema_revision_is_refused():
    for binding in ({'table': 'clients', 'id_column': 'id'}, {'table': 'clients', 'id_column': 'id', 'verified_revision': ''}):
        with pytest.raises(ErpGateError):
            ErpReader(FakeErp(), ADMITTED, binding).existing_ids([1])


def test_unsafe_identifiers_in_a_binding_are_refused():
    for bad in ('clients; DROP TABLE x', 'a b', 'x--', ''):
        with pytest.raises(ErpGateError):
            ErpReader(FakeErp(), ADMITTED, dict(BINDING, table=bad)).existing_ids([1])


# --- the query validator ------------------------------------------------------------------------------------------
@pytest.mark.parametrize('sql', [
    'DELETE FROM clients', 'UPDATE clients SET id=1', 'INSERT INTO clients VALUES (1)', 'DROP TABLE clients', 'SELECT 1; SELECT 2',
    'SELECT 1; DROP TABLE x', '/* hi */ SELECT 1', 'SELECT 1 -- hi', 'WITH x AS (DELETE FROM t RETURNING 1) SELECT * FROM x',
    'SELECT id FROM clients LIMIT 101', 'SELECT id FROM clients LIMIT 100000', 'CALL do_it()', 'PRAGMA table_info(x)',
    'SELECT * FROM clients INTO OUTFILE "/tmp/x"', '  ', 'SELECT id FROM clients FOR UPDATE',
])
def test_the_validator_rejects_anything_but_a_bounded_single_select(sql):
    with pytest.raises(ErpQueryError):
        validate_query(sql, 100)


def test_the_validator_adds_a_limit_and_keeps_safe_selects():
    assert validate_query('SELECT id FROM clients', 100).endswith('LIMIT 100')
    assert validate_query('select id from clients limit 5;', 100) == 'select id from clients limit 5'
    assert validate_query('SELECT id FROM clients WHERE name = \'a;b\' LIMIT 3', 100).endswith('LIMIT 3')


# --- the reader ---------------------------------------------------------------------------------------------------
def test_existing_ids_uses_only_the_one_read_tool_and_returns_ids():
    erp = FakeErp(existing={1, 3})
    assert reader(erp).existing_ids([1, 2, 3]) == {1, 3}
    assert [c[0] for c in erp.calls] == ['execute_read_only_query']
    assert 'LIMIT' in erp.calls[0][1]['query'] and 'name' not in erp.calls[0][1]['query'].lower()


def test_identifiers_are_double_quoted_so_mixed_case_tables_work():
    erp = FakeErp(existing={7})
    ErpReader(erp, ADMITTED, dict(BINDING, table='TM_CLI_CLient', id_column='cli_id')).existing_ids([7])
    query = erp.calls[0][1]['query']
    assert query.startswith('SELECT "cli_id" FROM "TM_CLI_CLient" WHERE "cli_id" IN (7)') and query.endswith('LIMIT 100')


def test_the_reader_never_calls_the_excluded_or_any_other_tool():
    erp = FakeErp()
    r = reader(erp)
    with pytest.raises(ErpGateError):
        r.call_tool('record_count', {'table': 'clients'})
    with pytest.raises(ErpGateError):
        r.call_tool('update_stock', {})
    assert erp.calls == []


def test_ids_must_be_integers_and_batches_are_bounded():
    with pytest.raises(ErpQueryError):
        reader().existing_ids(['1; DROP TABLE x'])
    erp = FakeErp(existing=set(range(250)))
    assert reader(erp).existing_ids(list(range(250))) == set(range(250))
    assert len(erp.calls) == 3  # 100 + 100 + 50, each within the row cap


def test_truncated_or_failed_responses_are_errors_not_partial_answers():
    with pytest.raises(ErpQueryError):
        reader(FakeErp(existing={1}, truncated=True)).existing_ids([1])
    with pytest.raises(ErpQueryError):
        reader(FakeErp(success=False)).existing_ids([1])


def test_a_response_larger_than_the_cap_is_refused():
    big = lambda tool, args: {'success': True, 'columns': ['id'], 'rows': [[i] for i in range(101)], 'row_count': 101, 'truncated': False, 'error': None}
    with pytest.raises(ErpQueryError):
        reader(big).existing_ids([1])


# --- verifying vault links ----------------------------------------------------------------------------------------
@pytest.fixture
def linked_vault(tmp_path):
    v = Vault(tmp_path / 'm' / 'v.sqlite', 'marketing', key_provider=lambda: 'k' * 32)
    (tmp_path / 'c.csv').write_text('email,company,account_id,segment\na@example.test,A,101,s\nb@example.test,B,202,s\nc@example.test,C,303,s\n')
    (tmp_path / 'a.csv').write_text('account_id,company,status,revenue_tier,transactions_basis,erp_invoices,erp_quotes,client_since\n101,A,x,x,erp_invoices,1,1,\n202,B,x,x,erp_invoices,1,1,\n303,C,x,x,erp_invoices,1,1,\n')
    v.ingest_contacts('axtech', tmp_path / 'c.csv')
    v.link_erp('axtech', tmp_path / 'a.csv')
    return v


def test_verify_links_records_which_references_exist_without_touching_contacts(linked_vault):
    result = verify_links(linked_vault, reader(FakeErp(existing={101, 303})), 'axtech', actor='axio')
    assert result == {'checked': 3, 'confirmed': 2, 'missing': 1}
    rows = dict(sqlite3.connect(linked_vault.path).execute('select erp_ref, exists_in_erp from erp_link_checks').fetchall())
    assert rows == {'erp_axtech:client:101': 1, 'erp_axtech:client:202': 0, 'erp_axtech:client:303': 1}
    assert sqlite3.connect(linked_vault.path).execute('select count(*) from contacts where erp_ref is not null').fetchone()[0] == 3
    assert linked_vault.audit_tail(1)[0]['action'] == 'verify_erp_links'


def test_verify_links_is_blocked_by_the_gate_and_records_nothing(linked_vault):
    with pytest.raises(ErpGateError):
        verify_links(linked_vault, ErpReader(FakeErp(), dict(ADMITTED, status='reference_contract_located_not_admitted'), BINDING), 'axtech', actor='axio')
    assert sqlite3.connect(linked_vault.path).execute('select count(*) from erp_link_checks').fetchone()[0] == 0


# --- CLI ----------------------------------------------------------------------------------------------------------
def run_cli(*args):
    import subprocess
    return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' / 'erp_verify_links.py'), *args], capture_output=True, text=True)


def write(tmp_path, contract, binding):
    c, b = tmp_path / 'contract.json', tmp_path / 'binding.json'
    c.write_text(json.dumps(contract)); b.write_text(json.dumps(binding))
    return str(c), str(b)


def test_cli_status_lists_every_unmet_gate_for_a_contract_that_is_only_located(tmp_path):
    located = {'status': 'reference_contract_located_not_admitted', 'required_before_live_use': ['verified target environment']}
    c, b = write(tmp_path, located, {})
    done = run_cli('--contract', c, '--binding', b, '--status')
    report = json.loads(done.stdout)
    assert done.returncode == 3 and report['ready'] is False
    assert any('not admitted' in u for u in report['unmet']) and any('verified schema revision' in u for u in report['unmet'])
    assert report['required_before_live_use'] == ['verified target environment']


def test_cli_status_is_ready_only_when_contract_and_binding_are_complete(tmp_path):
    c, b = write(tmp_path, ADMITTED, BINDING)
    done = run_cli('--contract', c, '--binding', b, '--status')
    assert done.returncode == 0 and json.loads(done.stdout)['ready'] is True


def test_cli_refuses_to_run_when_blocked_even_with_a_transport(tmp_path):
    c, b = write(tmp_path, dict(ADMITTED, status='reference_contract_located_not_admitted'), BINDING)
    done = run_cli('--contract', c, '--binding', b, '--vault', str(tmp_path / 'v.sqlite'), '--tenant', 't', '--actor', 'a', '--transport', 'os:getcwd')
    assert done.returncode == 3 and 'not admitted' in done.stderr


def test_cli_runs_with_an_admitted_contract_and_a_named_transport(tmp_path, linked_vault):
    (tmp_path / 'fake_transport.py').write_text(
        "import re\n"
        "def call(tool, arguments):\n"
        "    ids = [int(x) for x in re.search(r'IN \\(([^)]*)\\)', arguments['query']).group(1).split(',')]\n"
        "    rows = [[i] for i in ids if i in (101, 303)]\n"
        "    return {'success': True, 'columns': ['id'], 'rows': rows, 'row_count': len(rows), 'truncated': False, 'error': None}\n")
    c, b = write(tmp_path, ADMITTED, BINDING)
    import os, subprocess
    done = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' / 'erp_verify_links.py'), '--contract', c, '--binding', b,
                           '--vault', str(linked_vault.path), '--tenant', 'axtech', '--actor', 'axio', '--transport', 'fake_transport:call'],
                          capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(tmp_path)})
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {'checked': 3, 'confirmed': 2, 'missing': 1}
