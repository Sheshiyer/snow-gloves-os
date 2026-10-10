"""Offline ERP link: only numeric account ids are real ERP client ids; mail-derived keys stay unlinked."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib.tenant_vault import Vault, VaultError

CONTACTS = '''email,first_name,company,account_id,segment
a@example.test,A,Acme,101,erp_account
a2@example.test,A2,Acme,101,erp_account
b@example.test,B,Beta,202,erp_prospect
m@example.test,M,Mailco,mail:mailco.test,email_only_b2b
x@example.test,X,Ghost,999,erp_account
e@example.test,E,Echo,404,email_only_b2b
'''
ACCOUNTS = '''account_id,rank,company,segment,status,revenue_tier,transactions,transactions_basis,erp_invoices,invoiced_ht_eur,erp_quotes,client_since,last_activity
101,1,Acme,erp_account,active,high,40,erp_invoices,12,987654.32,30,2015-03-01,2026-09-01
202,2,Beta,erp_prospect,quoted,low,3,erp_invoices,0,0,5,2024-01-01,2025-01-01
mail:mailco.test,3,Mailco,email_only_b2b,unknown,low,2,email_client_documents,0,0,0,,
303,4,Delta,erp_account,dormant,mid,9,erp_invoices,4,12.5,6,2019-05-05,2024-02-02
404,5,Echo,email_only_b2b,unknown,low,1,email_client_documents,0,0,0,,
'''


@pytest.fixture
def marketing(tmp_path):
    v = Vault(tmp_path / 'm' / 'v.sqlite', 'marketing', key_provider=lambda: 'k' * 32)
    (tmp_path / 'c.csv').write_text(CONTACTS)
    (tmp_path / 'a.csv').write_text(ACCOUNTS)
    v.ingest_contacts('axtech', tmp_path / 'c.csv')
    return v, tmp_path / 'a.csv'


def refs(v):
    return {r[0]: r[1] for r in sqlite3.connect(v.path).execute('select email, erp_ref from contacts')}


def test_numeric_ids_that_the_erp_export_confirms_are_linked(marketing):
    v, accounts = marketing
    result = v.link_erp('axtech', accounts, snapshot='2026-09-22', source='accounts_master.csv')
    assert result == {'linked_accounts': 3, 'linked_contacts': 3, 'unlinked_contacts': 3, 'mail_only_accounts': 1}
    r = refs(v)
    assert r['a@example.test'] == r['a2@example.test'] == 'erp_axtech:client:101'
    assert r['b@example.test'] == 'erp_axtech:client:202'


def test_mail_derived_keys_and_ids_missing_from_the_export_stay_unlinked(marketing):
    v, accounts = marketing
    v.link_erp('axtech', accounts)
    r = refs(v)
    assert r['m@example.test'] is None      # mail-derived key: no ERP identity
    assert r['x@example.test'] is None      # numeric but the export never confirmed it: do not invent a link
    assert r['e@example.test'] is None      # numeric but the export's basis is email, not ERP invoices: not an ERP id


def test_relinking_is_idempotent_and_never_unlinks(marketing):
    v, accounts = marketing
    v.link_erp('axtech', accounts)
    again = v.link_erp('axtech', accounts)
    assert again['linked_contacts'] == 3 and refs(v)['a@example.test'] == 'erp_axtech:client:101'


def test_only_coarse_non_monetary_facts_are_kept_in_the_marketing_vault(marketing):
    v, accounts = marketing
    v.link_erp('axtech', accounts, snapshot='2026-09-22')
    cols = {r[1] for r in sqlite3.connect(v.path).execute('pragma table_info(erp_account_facts)')}
    assert not ({'invoiced_ht_eur', 'revenue', 'amount'} & cols)
    row = sqlite3.connect(v.path).execute("select erp_invoices, erp_quotes, client_since, snapshot from erp_account_facts where erp_ref='erp_axtech:client:101'").fetchone()
    assert row == (12, 30, '2015-03-01', '2026-09-22')
    assert '987654' not in v.path.read_bytes().decode('latin1')


def test_link_status_reports_counts_per_segment_without_any_address(marketing):
    v, accounts = marketing
    v.link_erp('axtech', accounts)
    status = v.erp_link_status('axtech')
    assert status['erp_account'] == {'contacts': 3, 'linked': 2, 'unlinked': 1}
    assert status['email_only_b2b'] == {'contacts': 2, 'linked': 0, 'unlinked': 2}
    assert '@' not in str(status)


def test_link_is_audited_and_marketing_only(marketing, tmp_path):
    v, accounts = marketing
    v.link_erp('axtech', accounts)
    assert v.audit_tail(1)[0]['action'] == 'link_erp'
    finance = Vault(tmp_path / 'f' / 'v.sqlite', 'finance', key_provider=lambda: 'k' * 32)
    with pytest.raises(VaultError):
        finance.link_erp('axtech', accounts)


def test_samples_say_whether_a_contact_is_erp_linked(marketing):
    v, accounts = marketing
    v.link_erp('axtech', accounts)
    sample = {r['company']: r for r in v.sample('erp_account', 10) + v.sample('email_only_b2b', 10)}
    assert sample['Acme']['erp_linked'] is True and sample['Mailco']['erp_linked'] is False
