"""Tenant vault: separate finance and marketing stores, IBANs encrypted at rest and masked by default,
contacts with suppression, every reveal and export audited."""
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.tenant_vault import Vault, VaultError, iban_valid, mask_email, mask_iban

IBAN_A = 'FR76 3000 6000 0112 3456 7890 189'   # standard example IBAN, valid checksum
IBAN_B = 'DE89 3704 0044 0532 0130 00'          # standard example IBAN, valid checksum
IBAN_BAD = 'FR76 3000 6000 0112 3456 7890 188'  # wrong checksum
KEY = lambda: 'test-key-' + 'k' * 24

BANK_MD = f'''# SOLD
### 4.1 Legal entities
| Entity | SIREN | VAT | Seat (city) | Signatory / note |
|---|---|---|---|---|
| SCI ALPHA | 883 502 296 | FR39883502296 | Courtry | note |
| SCI BETA | 892 616 491 | FR70892616491 | Paris | |
### 4.2 Banking connections on file (SCIs)
| Entity | Bank (BIC) | IBAN |
|---|---|---|
| **GARY / AX TECH** | CIC (CMCIFR2A) | {IBAN_A}|
| SCI BETA | (PREUFRP1) | {IBAN_B} |
| SCI BROKEN | BRED (BREDFRPP) | {IBAN_BAD} |
| SCI ALPHA | Banque Populaire (CGBPFRPP) | {IBAN_A} |
'''

CONTACTS = '''﻿email,first_name,last_name,display_name,company,account_id,segment,group,business_line,account_status,revenue_tier
Jane.Doe@Example.test,Jane,Doe,Jane Doe,Acme,A1,01_active_clients,g1,ECOLED,active,high
bob@example.test,Bob,Roe,Bob Roe,Beta,B2,02_winback_dormant,g2,WAVE,dormant,low
not-an-email,X,Y,X Y,Gamma,C3,01_active_clients,g1,ECOLED,active,low
jane.doe@example.test,Jane,Doe,Jane Doe,Acme,A1,01_active_clients,g1,ECOLED,active,high
stop@example.test,Stop,Me,Stop Me,Delta,D4,01_active_clients,g1,ECOLED,active,mid
'''
SUPPRESSION = '﻿email,reason,detail\nSTOP@example.test,unsubscribed,asked\n'


@pytest.fixture
def finance(tmp_path):
    return Vault(tmp_path / 'finance' / 'vault.sqlite', 'finance', key_provider=KEY)


@pytest.fixture
def marketing(tmp_path):
    return Vault(tmp_path / 'marketing' / 'vault.sqlite', 'marketing', key_provider=KEY)


def test_helpers():
    assert iban_valid(IBAN_A) and iban_valid(IBAN_B) and not iban_valid(IBAN_BAD) and not iban_valid('nonsense')
    assert mask_iban(IBAN_A) == 'FR76 **** 0189'
    assert mask_email('Jane.Doe@Example.test') == 'j***@example.test'
    assert mask_email('not-an-email') == '***'


def test_store_is_private_and_domains_are_separate(finance, marketing, tmp_path):
    for vault in (finance, marketing):
        assert stat.S_IMODE(os.stat(vault.path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(vault.path.parent).st_mode) == 0o700
    with pytest.raises(VaultError):
        marketing.ingest_bank_markdown('t', BANK_MD, 'x')
    with pytest.raises(VaultError):
        finance.ingest_contacts('t', tmp_path / 'c.csv')
    with pytest.raises(VaultError):
        Vault(tmp_path / 'x.sqlite', 'ops', key_provider=KEY)
    names = lambda v: {r[0] for r in sqlite3.connect(v.path).execute("select name from sqlite_master where type='table'")}
    assert 'bank_accounts' in names(finance) and 'contacts' not in names(finance)
    assert 'contacts' in names(marketing) and 'bank_accounts' not in names(marketing)


def test_iban_ingest_encrypts_dedupes_and_reports_bad_rows(finance):
    result = finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    assert result['accounts_added'] == 2 and result['invalid'] == ['SCI BROKEN']
    assert result['entities_added'] == 2
    again = finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    assert again['accounts_added'] == 0 and again['accounts_existing'] == 2 and len(finance.accounts()) == 2
    raw = finance.path.read_bytes() + b''.join(p.read_bytes() for p in finance.path.parent.glob('*-wal'))
    for digits in (IBAN_A, IBAN_B, IBAN_A.replace(' ', ''), IBAN_B.replace(' ', ''), '30006000011234567890189'):
        assert digits.encode() not in raw


def test_accounts_are_masked_and_carry_bank_and_bic(finance):
    finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    rows = {r['entity']: r for r in finance.accounts()}
    assert rows['GARY / AX TECH']['iban'] == 'FR76 **** 0189'
    assert (rows['GARY / AX TECH']['bank'], rows['GARY / AX TECH']['bic']) == ('CIC', 'CMCIFR2A')
    assert rows['SCI BETA']['bank'] == '' and rows['SCI BETA']['bic'] == 'PREUFRP1'
    assert all('iban_enc' not in r and 'iban_hash' not in r for r in rows.values())
    assert {e['name'] for e in finance.entities()} == {'SCI ALPHA', 'SCI BETA'}
    assert next(e for e in finance.entities() if e['name'] == 'SCI ALPHA')['siren'] == '883502296'


def test_verify_iban_matches_without_revealing(finance):
    finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    assert finance.verify_iban('SCI BETA', IBAN_B.replace(' ', '').lower()) is True
    assert finance.verify_iban('SCI BETA', IBAN_A) is False
    assert finance.verify_iban('NOBODY', IBAN_A) is False


def test_reveal_needs_actor_and_reason_and_is_audited(finance):
    finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    account = next(r for r in finance.accounts() if r['entity'] == 'SCI BETA')
    for actor, reason in (('', 'because'), ('human', ''), ('human', '  ')):
        with pytest.raises(VaultError):
            finance.reveal_iban(account['id'], actor, reason)
    assert finance.reveal_iban(account['id'], 'axio', 'monthly reconciliation') == IBAN_B.replace(' ', '')
    entry = finance.audit_tail(1)[0]
    assert (entry['actor'], entry['action']) == ('axio', 'reveal_iban') and 'monthly reconciliation' in entry['detail']
    with pytest.raises(VaultError):
        finance.reveal_iban(99999, 'axio', 'x')
    assert IBAN_B.replace(' ', '') not in str(finance.audit_tail(50))


def test_a_different_key_cannot_decrypt(finance, tmp_path):
    finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    other = Vault(finance.path, 'finance', key_provider=lambda: 'another-key-' + 'z' * 24)
    account = other.accounts()[0]
    with pytest.raises(VaultError):
        other.reveal_iban(account['id'], 'axio', 'attempt')


def write_csvs(tmp_path):
    (tmp_path / 'contacts.csv').write_text(CONTACTS, encoding='utf-8')
    (tmp_path / 'suppression.csv').write_text(SUPPRESSION, encoding='utf-8')
    return tmp_path / 'contacts.csv', tmp_path / 'suppression.csv'


def test_contact_ingest_normalizes_dedupes_and_applies_suppression(marketing, tmp_path):
    contacts, suppression = write_csvs(tmp_path)
    result = marketing.ingest_contacts('axtech', contacts, suppression, source='contacts_master.csv')
    assert result == {'contacts_added': 3, 'duplicates': 1, 'invalid': 1, 'suppressed': 1, 'contacts_existing': 0}
    again = marketing.ingest_contacts('axtech', contacts, suppression, source='contacts_master.csv')
    assert again['contacts_added'] == 0 and again['contacts_existing'] == 3
    assert marketing.is_suppressed('stop@EXAMPLE.test') is True
    assert marketing.is_suppressed('bob@example.test') is False
    assert marketing.is_suppressed('unknown@example.test') is False


def test_segment_counts_separate_reachable_from_suppressed(marketing, tmp_path):
    contacts, suppression = write_csvs(tmp_path)
    marketing.ingest_contacts('axtech', contacts, suppression)
    counts = marketing.segment_counts('axtech')
    assert counts['01_active_clients'] == {'total': 2, 'suppressed': 1, 'reachable': 1}
    assert counts['02_winback_dormant'] == {'total': 1, 'suppressed': 0, 'reachable': 1}


def test_samples_are_masked_capped_and_exclude_suppressed(marketing, tmp_path):
    contacts, suppression = write_csvs(tmp_path)
    marketing.ingest_contacts('axtech', contacts, suppression)
    rows = marketing.sample('01_active_clients', limit=500)
    assert len(rows) == 1 and rows[0]['email'] == 'j***@example.test' and rows[0]['company'] == 'Acme'
    assert len(marketing.sample('01_active_clients', limit=0)) == 0
    assert all('@' not in r['email'].split('@')[0] for r in rows)


def test_sample_limit_is_capped_even_when_asked_for_more(marketing, tmp_path):
    lines = ['email,segment'] + ['u%d@example.test,s' % i for i in range(120)]
    (tmp_path / 'many.csv').write_text('\n'.join(lines))
    marketing.ingest_contacts('axtech', tmp_path / 'many.csv')
    assert len(marketing.sample('s', limit=10_000)) == 25


def test_export_writes_a_private_file_without_suppressed_and_is_audited(marketing, tmp_path):
    contacts, suppression = write_csvs(tmp_path)
    marketing.ingest_contacts('axtech', contacts, suppression)
    out = tmp_path / 'exports' / 'active.csv'
    assert marketing.export_segment('01_active_clients', out, 'axio', 'approved spring campaign') == 1
    text = out.read_text()
    assert 'jane.doe@example.test' in text and 'stop@example.test' not in text
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    entry = marketing.audit_tail(1)[0]
    assert entry['action'] == 'export_segment' and '1 rows' in entry['detail'] and 'jane.doe@example.test' not in str(marketing.audit_tail(20))
    with pytest.raises(VaultError):
        marketing.export_segment('01_active_clients', out, 'axio', 'again')  # never overwrites
    with pytest.raises(VaultError):
        marketing.export_segment('01_active_clients', tmp_path / 'x.csv', '', 'no actor')
    with pytest.raises(VaultError):
        marketing.export_segment('01_active_clients', tmp_path / 'y.csv', 'axio', ' ')


def test_erp_reference_columns_exist_for_the_last_integration_step(finance, marketing):
    cols = lambda v, t: {r[1] for r in sqlite3.connect(v.path).execute('pragma table_info(%s)' % t)}
    assert 'erp_ref' in cols(marketing, 'contacts') and 'erp_ref' in cols(finance, 'entities') and 'erp_ref' in cols(finance, 'bank_accounts')


def run_cli(tmp_path, *args, env=None):
    import subprocess
    cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' / 'tenant_vault.py'), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, 'SNOWGLOVES_VAULT_KEY': 'cli-key-' + 'c' * 24, **(env or {})})


def test_cli_round_trip_with_masked_output_and_logged_reveal(tmp_path):
    md = tmp_path / 'sold.md'; md.write_text(BANK_MD)
    vault = str(tmp_path / 'v' / 'f.sqlite')
    done = run_cli(tmp_path, '--vault', vault, '--domain', 'finance', 'ingest-bank', '--tenant', 'axtech', '--file', str(md))
    assert done.returncode == 0 and '"accounts_added": 2' in done.stdout
    listing = run_cli(tmp_path, '--vault', vault, '--domain', 'finance', 'accounts')
    assert 'FR76 **** 0189' in listing.stdout and '30006000011234567890189' not in listing.stdout
    assert run_cli(tmp_path, '--vault', vault, '--domain', 'finance', 'reveal', '--id', '1', '--actor', 'axio', '--reason', '').returncode == 1
    shown = run_cli(tmp_path, '--vault', vault, '--domain', 'finance', 'reveal', '--id', '1', '--actor', 'axio', '--reason', 'reconcile')
    assert shown.returncode == 0 and shown.stdout.strip() in (IBAN_A.replace(' ', ''), IBAN_B.replace(' ', ''))
    assert 'reveal_iban' in run_cli(tmp_path, '--vault', vault, '--domain', 'finance', 'audit').stdout


def test_cli_rejects_the_wrong_domain_for_a_command(tmp_path):
    vault = str(tmp_path / 'v' / 'm.sqlite')
    assert run_cli(tmp_path, '--vault', vault, '--domain', 'marketing', 'accounts').returncode == 1


def test_mcp_server_exposes_only_safe_tools(finance, marketing, tmp_path):
    pytest.importorskip('mcp.server')
    import asyncio
    from vault_mcp import create_server
    names = lambda v: sorted(t.name for t in asyncio.run(create_server(v).list_tools()))
    assert names(finance) == ['finance_accounts', 'finance_entities', 'finance_verify_iban']
    assert names(marketing) == ['marketing_erp_link_status', 'marketing_is_suppressed', 'marketing_sample', 'marketing_segments']
    for forbidden in ('reveal', 'export', 'iban_enc'):
        assert not any(forbidden in n for n in names(finance) + names(marketing))


def test_mcp_tools_work_from_worker_threads_and_never_return_full_values(finance, marketing, tmp_path):
    pytest.importorskip('mcp.server')
    import asyncio
    import json
    from vault_mcp import create_server
    finance.ingest_bank_markdown('axtech', BANK_MD, 'sold.md')
    contacts, suppression = write_csvs(tmp_path)
    marketing.ingest_contacts('axtech', contacts, suppression)

    async def call(server, name, args):
        result = await server.call_tool(name, args)
        return json.dumps(result, default=str)
    out = asyncio.run(call(create_server(finance), 'finance_accounts', {}))
    assert 'FR76 **** 0189' in out and '30006000011234567890189' not in out
    assert 'true' in asyncio.run(call(create_server(finance), 'finance_verify_iban', {'entity': 'SCI BETA', 'iban': IBAN_B})).lower()
    out = asyncio.run(call(create_server(marketing), 'marketing_sample', {'segment': '01_active_clients', 'limit': 5}))
    assert 'j***@example.test' in out and 'jane.doe@example.test' not in out and 'stop@' not in out
