# Fleet decisions

Dated log, newest first. Each entry records the decision, why, what it changes, and when it is reviewed.
Decisions here bind this repo. Where one overrides a host-side document under `~/.temperance_engine`,
the host document must be amended by the operator; this log does not edit it.

## 2026-10-02

### (a) Tailscale is the fleet overlay

- Decision: every fleet Mac and every team Mac joins one company tailnet. Fleet services are addressed by
  MagicDNS name (`coding-mac`, `marketing-mac`, `design-mac`), never by office LAN IP.
- Why: stable names across networks and travel, device identity and ACLs for free, no port forwarding,
  Taildrop for the handoff kit.
- Consequences: `fleet.yaml` carries overlay names only. The gateway binds to its tailnet address. The
  authoring mini must install Tailscale (it has none today). ACL: tcp/20128 to `coding-mac` from company devices only.

### (b) The Coding Mac in Paris hosts the gateway; the founder's mini is the authoring seat

- Decision: OmniRoute for the whole fleet runs on the always-on Coding Mac (`gateway.wing: coding`,
  port 20128). The founder's current mini is `authoring_seat` with role `staging`: it authors config and
  exports the handoff kit, and keeps its own local OmniRoute on loopback for its own work.
- Why: one always-on machine, one set of provider seats, one place to rotate keys and read logs. The
  authoring mini travels and sleeps.
- Consequences: `scripts/fleet/gateway_kit.sh export | verify | import`; `docs/fleet/04-GATEWAY.md`.
  Host-local clients on the Coding Mac use `coding-mac:20128` because loopback is not bound.

### (c) One company Apple Account and one shared operator user per wing

- Decision: each wing mini has a local admin `sg-admin` and one shared operator user `sg-<wing>`
  (`sg-marketing`, `sg-design`, `sg-coding`). One company Apple Account is used for machine setup and
  the App Store. Personal Apple IDs are never signed in on wing minis.
- Why: three machines, small teams, zero per-person macOS account churn. Accountability comes from
  per-person scoped gateway keys, git identity and the tailnet device record, not from macOS users.
- Consequences: Keychain items are per wing (`snowgloves-gateway-<wing>`). Screen lock and Screen Sharing
  are mandatory on the operator user. The shared password lives in the company password manager.

### (d) Subscription seats are shared through the gateway now; terms are confirmed later

- Decision: all provider seats are shared through the fleet gateway immediately, including the
  subscription seats (Claude Max, ChatGPT Codex, SuperGrok, Cursor, Antigravity, Command Code), not only
  the pay-per-token API keys. Provider terms for multi-user gateway use are to be confirmed afterwards.
- Overrides: `~/.temperance_engine/docs/decisions/ACP-INTEGRATION-2026-08-24.md` rule #4 (open question
  4: "Is serving a subscription seat through a network-bound gateway permissible under seat terms? NO,
  treat as prohibited until the operator says otherwise"). The operator has now said otherwise, on this date.
- Risk, stated plainly: a provider may read shared use of a personal subscription as a terms violation
  and suspend the account, which would take that seat away from every wing at once. The exposure is
  larger on a network-bound gateway than on loopback because more clients and more people are visible
  as one account.
- Mitigations:
  1. Bind only to the Tailscale address, never `0.0.0.0`; no office LAN or internet exposure.
  2. One scoped key per machine and per person (`allowed_endpoints`, `allowed_combos`, `ip_allowlist`,
     `daily_usage_limit_usd`), so usage is attributable and revocable per key.
  3. Rotate the dashboard password at import; the admin key never leaves the host.
  4. Keep the subscription OAuth sign-ins on the Coding Mac only; they never enter the kit or git.
  5. Terms-review trigger below; if any provider's terms prohibit it, that seat is moved back to
     `is_active=0` in the gateway the same day and the wing falls back to API-key seats.
- Review trigger: confirm Anthropic, OpenAI and xAI subscription terms for multi-user gateway use;
  revisit by 2026-11-01. Record the outcome as a new dated entry here.
- Required host-side step (operator, outside this repo): amend rule #4 in the ACP decision document
  with this dated override and a pointer to this file. Do not delete the original wording.

## Pending review

| Due | Item | Owner |
|---|---|---|
| 2026-11-01 | Subscription terms for multi-user gateway use (Anthropic, OpenAI, xAI); also Cursor, Google Antigravity, Command Code | founder |
| at import | Rotate the OmniRoute dashboard password on the Coding Mac | gateway operator |
| at import | Amend ACP rule #4 on the host; fix the `omniroute` MCP key scope (`mcp-connect`) | gateway operator |
| before export | Install Tailscale on the authoring mini | founder |
