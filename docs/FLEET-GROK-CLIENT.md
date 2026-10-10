# Grok Bot fleet client

Grok Bot is an optional operational client. The coordinator, Hermes, worker,
production UI and inference gateway run independently of the desktop app.

The installed app's supported **Bot Plugins → Add custom** flow accepts one
MCP server per imported JSON configuration. Register through that flow; do not
modify the signed app bundle or guess a local settings-file schema. Its local
`mcpBoxServers` setting is an array of names, not a server configuration map.

Prefer a client-placed authenticated HTTP plugin so an account-backed box
executor does not need to resolve an operator Mac's filesystem paths:

```json
{
  "mcpServers": {
    "snowgloves-fleet": {
      "type": "http",
      "url": "https://fleet.hey-zack.fr/api/mcp",
      "headers": {"Authorization": "Bearer REPLACE_IN_PRIVATE_IMPORT_FILE"},
      "placement": "client"
    }
  }
}
```

The real import file belongs in the private operations runtime, mode0600, with a
dedicated application token. Never use founder, worker or gateway-admin tokens.
The application principal should have only its explicitly assigned project and
`read`, `submit`, `cancel` permissions. Approval is a separate founder permission.
A private Tailscale route to Coding01 TCP443 is required; this endpoint does not
make the company fleet or inference gateway public.

The HTTP sidecar (`scripts/fleet_mcp_http.py`) binds loopback, accepts only the
configured application bearer credential, validates host/origin before MCP
parsing, and exposes stateless JSON MCP over POST `/mcp`. The production web
server forwards `/api/mcp` to it without exposing worker or administrative routes.
The sidecar uses the installed Hermes MCP SDK interpreter, not a guessed system
Python. No interactive shell or login Keychain is required.

The tools cover task submission/list/status/events/cancellation/fan-out,
authorized context, catalog readiness/execution, approval requests/decisions and
verified artifact retrieval. The coordinator enforces permissions even when the
client discovers a tool it cannot invoke. Reuse the same idempotency key when
retrying an uncertain submission; inspect the existing task before starting a
new action. A recovery hold never authorizes replay.

Acceptance requires discovery in the actual signed app, a bounded submission,
the same task ID in the UI, verified artifact retrieval, cancellation and
continued backend execution with the app closed. SDK discovery alone proves
only the transport. Keep external messaging disabled unless separately selected.
