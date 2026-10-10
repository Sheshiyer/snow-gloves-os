# Tenant vaults: restricted finance and marketing data

Some tenant data must be usable by agents but must not live in git or in the shared knowledge base: bank identifiers and contact lists. Each is held in its own local vault, one SQLite file per domain, outside every git repo.

| Domain | Holds | Agents get | Humans only |
|---|---|---|---|
| `finance` | legal entities (SIREN, VAT), bank accounts | bank, BIC, **masked** IBAN, `verify_iban` (true/false) | `reveal` (actor + reason, audited) |
| `marketing` | contacts, do-not-contact list | segment counts, **masked** capped samples, `is_suppressed` | `export` to a private file (actor + reason, audited, never overwrites) |

## Why not the knowledge base
The knowledge base is embedded and retrieved through hosted models. Putting IBANs or 100k addresses there would send them to a provider on every retrieval. Vault values reach a model only through an explicit, logged reveal or export.

## Guarantees (each covered by a test that fails when it is removed)
- IBANs are AES-256 encrypted at rest (OpenSSL, per-domain key in the macOS Keychain, service `snowgloves-tenant-vault`); the file holds only masked forms and an HMAC fingerprint. FileVault is off on Coding 01, so this matters.
- Only IBANs that pass the mod-97 checksum are stored; rows that fail are reported by entity name.
- A vault refuses the other domain's operations, and an agent runtime is given only its own file.
- Suppression always wins: suppressed addresses never appear in samples or exports.
- Samples are capped at 25 and masked; audit entries never contain an IBAN or an address.

## Use
```sh
tenant_vault.py --vault V --domain finance   ingest-bank     --tenant axtech --file sold.md
tenant_vault.py --vault V --domain marketing ingest-contacts --tenant axtech --contacts contacts_master.csv --suppression do_not_contact.csv
tenant_vault.py --vault V --domain finance   accounts | entities | audit
tenant_vault.py --vault V --domain finance   reveal --id N --actor NAME --reason "..."
tenant_vault.py --vault V --domain marketing export --segment S --dest FILE --actor NAME --reason "..."
```
Agents use `scripts/vault_mcp.py --domain finance|marketing` (read-only tools, no reveal, no export). The catalog cards `snowgloves-vault-finance` and `snowgloves-vault-marketing` describe the launch spec; a tenant must enable them in `enabled.yaml` and set `SNOWGLOVES_VAULT_FINANCE` / `SNOWGLOVES_VAULT_MARKETING` to its vault files. Enabling is a founder decision and is not done by default.

## Key custody
The key is created on first use. **Losing it makes the IBANs unrecoverable**; keep an offline copy of the Keychain item (`security find-generic-password -s snowgloves-tenant-vault -a finance -w`) in the founder's recovery custody. Rotating means re-ingesting from the source file.

## Importing a tenant branch
`scripts/tenant_import_plan.py` is a read-only planner: it classifies a source ref's changed tenant files into T0 restricted, T1 internal, T2 knowledge by path and by content (valid IBANs, credentials, contact exports), compares them with the destination and trial-merges. Import only the include list as a plain commit (not a merge of the source history), and load T0 files into the vaults.

## ERP link

Two layers, so the part that is evidenced works today and the live part stays behind the founder's contract.

**1. Offline link (done on Coding 01).** `tenant_vault.py link-erp` reads the ERP-derived account export and links contacts to confirmed ERP client references (`erp_axtech:client:<id>`). Only numeric account ids whose export basis is `erp_invoices` count as ERP ids; mail-derived keys (`domain:name@...`) and ids the export never confirmed stay unlinked, and nothing is ever unlinked. The marketing vault keeps coarse non-monetary facts only (invoice and quote counts, status, tier); money is not copied into it. Agents see `marketing_erp_link_status` and an `erp_linked` flag on masked samples. On the axtech data: 5,867 of 9,127 contacts linked, covering 784 ERP clients, with every contact in an ERP-sourced segment linked and none of the mail-derived ones.

**2. Live verification (built, blocked by design).** `lib/erp_reader.py` enforces `specs/ai-commercial-organization/erp-reference-contract.json` in code: the contract must be `admitted` with mutation tools disabled; one read tool only (never `record_count`); a single bounded SELECT (no comments, no second statement, no write or locking keyword, LIMIT at most 100, truncated answers refused); identifiers come from a binding that names a verified schema revision; ids only, no customer fields. `erp_verify_links.py --status` prints what is still unmet; running needs a named transport (`module:function`) that talks to the `erp_axtech` endpoint with the per-brand credential, which is not part of this repository. Results go to `erp_link_checks` and the audit log; contacts are never changed by a check.

Not implemented on purpose: any ERP write, any customer-record read, any finance-side client revenue copy (decide whether the finance agent needs it first).
