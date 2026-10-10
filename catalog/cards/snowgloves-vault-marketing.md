---
id: snowgloves-vault-marketing
name: "Snow Gloves Vault: marketing"
category: mcp
kind: mcp-server
disposition: add
repo: "scripts/vault_mcp.py"
source: "compress-integration-2026-10-10"
risk: high
approval: yes
agents: [chief-of-staff]
hooks: []
runtimes: [any]
summary: "Read-only view of a tenant's contacts: segment counts, masked samples, do-not-contact checks. Full address lists leave only through a logged human export."
mcp:
  command: snowgloves-vault-mcp
  args: ["--domain", "marketing"]
  env:
    SNOWGLOVES_VAULT_PATH: "${SNOWGLOVES_VAULT_MARKETING}"
---

# Snow Gloves Vault: marketing

First-party MCP server over the tenant's local marketing vault (`scripts/lib/tenant_vault.py`). Tools: `marketing_segments`, `marketing_sample` (masked, capped at 25), `marketing_is_suppressed`. There is no export tool: a person runs `tenant_vault.py export`, which refuses to overwrite and writes an audit entry.

The contact data is **not** in the knowledge base and is not embedded. Suppression always wins. Sending anything stays behind the tenant's own approval rule; this server cannot send.

Nothing here grants access: the tenant must enable `snowgloves-vault-marketing` in `enabled.yaml` and point `SNOWGLOVES_VAULT_MARKETING` at its vault file (a 0600 file in a 0700 directory outside any git repo). The vault key lives in the macOS Keychain, not in the environment.
