# Grok Bot fleet client

Grok Bot is an optional operational client. The coordinator, Hermes, worker,
production UI and inference gateway run independently of the desktop app.

Use **Bot Plugins → Add custom** only when that supported flow is visible in
the actual installed app. The documented import accepts one MCP server per JSON
configuration. If this app version or account does not expose custom import,
record the app version, visible controls and missing capability as a blocker;
stop registration there. Do not modify the signed app bundle, invent a settings
schema or treat a different Connect Apps screen as successful registration.
`mcpBoxServers` is an array of names, not a server configuration map.

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

## Registration and acceptance procedure

Run these checks from the operator's actual Grok Bot app on Coding01. A terminal
MCP probe can establish transport readiness, but cannot complete an app check.
Keep receipts in the private operations checkout; redact credentials, import
contents and private message text from screenshots and logs.

1. Confirm the machine identity and the signed app version. Confirm its client
   has the private Tailscale route and trusted HTTPS access to Coding01 TCP443.
   Verify the dedicated `grok-bot` principal's assigned project and permissions
   with the installed service configuration. Do not substitute a founder token
   to make an authorization failure pass.
2. Open the supported custom-plugin import if visible. Import the existing
   mode0600 private runtime file containing the dedicated application token;
   the JSON above is a template, not a usable credential. Keep `placement` set
   to `client`. If the app rejects that configuration or cannot reach the
   private endpoint, record the actual error and stop; do not publish the
   endpoint or switch execution placement as a workaround.
3. In the actual app, discover the registered server's tools and call
   `fleet_context`. Record the returned project and permissions without tokens.
   Compare discovery with the installed server's tools; do not use a hard-coded
   tool count as the acceptance criterion. Discovery of approval tools does
   not grant the application approval authority.
4. Submit one bounded read-only canary through `fleet_submit`, using the exact
   authorized project returned above, `access="read"`, and a fresh idempotency
   key recorded before submission. The brief should request a short summary
   from one existing project document, explicitly forbidding edits, commands
   that change state, external messages, deployments and service restarts.
   Do not fan out or request write access for this registration canary. Save
   the returned task ID. For an uncertain response, inspect `fleet_list` and
   retry only with the same key and identical arguments; never generate another
   key merely because the app timed out.
5. Open the production board using its supported authenticated flow. Verify
   that its task ID equals the ID returned to Grok Bot. Inspect
   `fleet_status` and `fleet_logs` for that same ID through the app until it
   reaches a terminal state. A provider failure or recovery hold is a failed
   execution check, even when submission and discovery worked; do not replay it.
6. For a successful canary, retrieve `fleet_artifact` through the app. Record
   the verified source digest and compare it with the board's artifact receipt
   for the same task. If the board does not expose a comparable digest, leave
   artifact equality pending until a supported authenticated receipt can supply
   it. Do not claim equality from matching summary text or an artifact pathname.
7. Test cancellation with a **separate** read-only canary and a new recorded
   idempotency key. Cancel that task through `fleet_cancel` while it is queued,
   then verify the task's cancelled state in both app and board. Never cancel
   an unrelated task or the successful artifact canary. If it starts or finishes
   before cancellation, record the race as inconclusive; do not call a terminal
   task cancellation a successful queued cancellation check. Do not pause a
   shared worker merely to manufacture the queued state.
8. Test app independence with another separately identified bounded read-only
   task. Observe it queued or running, fully quit the Grok Bot app, and inspect
   the same task on the independently authenticated board. Record a status or
   event transition after the app quit. Reopen the app and retrieve that task's
   final status and verified artifact. A task already complete before closing
   the app proves no persistence. This check proves app independence only;
   worker reboot and physical coldboot require separate fleet evidence.

Do not enable external messaging, change backend service configuration, or
restart the fleet as part of these client acceptance steps.

## Evidence and remaining gates

Record each gate separately with timestamp, machine/app or source identity,
task IDs where relevant, observed result and a redacted evidence location:

| Gate | Evidence needed | What it establishes |
| --- | --- | --- |
| Source | Source revision, relevant tests and configuration schema | Implementation exists in that revision |
| Installation | Installed service paths, revision/digest, app version and machine identity | Which code and app are on the physical mini |
| Transport | Authenticated MCP discovery and scoped context from that installation | Endpoint reachability and authorization |
| Actual app registration | Supported import visible and server/tools discovered inside Grok Bot | The app uses the installed transport |
| App execution | App-originated task ID equals board ID; successful terminal task | The app can submit and follow a fleet task |
| Artifact | App-retrieved verified digest equals the board receipt | Both surfaces refer to the same verified result |
| Cancellation | Separate queued canary reaches cancelled state through the app | Bounded cancellation works |
| App independence | Backend transition after full app quit; same ID recovered afterward | Backend execution continues without the app |

Leave unobserved gates pending. An installed app, passing source tests, SDK
transport discovery, or a task submitted from a shell cannot substitute for
actual app acceptance. Physical mini reboot and coldboot receipts remain
separate from all of these gates.

## Read-only setup check

Validate the protected import without network access:

```bash
python3 scripts/fleet_grok_client.py /absolute/private/grok-bot.import.json
```

From a client with private network access, initialize MCP and list tools:

```bash
python3 scripts/fleet_grok_client.py /absolute/private/grok-bot.import.json --probe --timeout 10
```

The probe performs no tool calls or task submissions. It refuses redirects and
ambient proxies, bounds response size and pagination, and reports only redacted
transport evidence. The timeout applies per socket operation. Neither command
registers the app or proves app-originated execution.
