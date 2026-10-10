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

## ERP (last step)
Rows reserve a nullable `erp_ref`. Linking is read-only first: match `contacts.account_id` and `entities.siren` to the existing ERP through its reviewed read contract, behind `connector-gate`, then fill `erp_ref`. No ERP write and no bank or billing action is part of this.
