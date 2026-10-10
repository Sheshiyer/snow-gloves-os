---
id: snowgloves-vault-finance
name: "Snow Gloves Vault: finance"
category: mcp
kind: mcp-server
disposition: add
repo: "scripts/vault_mcp.py"
source: "compress-integration-2026-10-10"
risk: high
approval: yes
agents: [chief-of-staff, sentinel]
hooks: []
runtimes: [any]
summary: "Read-only view of a tenant's legal entities and bank accounts with masked IBANs, plus a match check. Full IBANs leave only through a logged human reveal."
mcp:
  command: snowgloves-vault-mcp
  args: ["--domain", "finance"]
  env:
    SNOWGLOVES_VAULT_PATH: "${SNOWGLOVES_VAULT_FINANCE}"
---

# Snow Gloves Vault: finance

First-party MCP server over the tenant's local finance vault. Tools: `finance_accounts` (bank, BIC, masked IBAN), `finance_entities` (SIREN, VAT), `finance_verify_iban` (true or false; never reveals a stored value). There is no reveal tool: a person runs `tenant_vault.py reveal` with an actor and a reason, which is audited.

IBANs are AES-256 encrypted at rest with a per-domain Keychain key and are **not** in the knowledge base or any embedding index, so they are never sent to a hosted model for retrieval. The server cannot move money, change billing or contact a bank.

Nothing here grants access: the tenant must enable `snowgloves-vault-finance` in `enabled.yaml` and point `SNOWGLOVES_VAULT_FINANCE` at its vault file.
