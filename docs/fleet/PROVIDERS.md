# Providers behind the fleet gateway

Names only. No keys, no account ids. Classes are taken from the host docs on the authoring seat
(`CLI-AGENTS.md`, `runbooks/PROVIDER-FLEET-RUNBOOK.md`) and from provider ids seen in the lane template
`~/.temperance_engine/state/lane-templates-from-live.json` on 2026-10-02. Where the docs do not say,
the row is marked unverified. The gateway host's `provider_connections` table is the authority; this
file is the shared summary. Procedure to add one: [04-GATEWAY.md](04-GATEWAY.md), "Add a provider".

## Classes

- **API key, pay per token.** One company key per provider, held by the gateway. Sharing is ordinary API use.
- **Subscription seat.** An OAuth or session sign-in tied to a plan (Claude Max, ChatGPT Codex, SuperGrok,
  Cursor, Antigravity, Command Code). Signed in once on the Coding Mac. Multi-user terms unconfirmed;
  see [DECISIONS.md](DECISIONS.md) entry 2026-10-02 (d).

## Roster

| Provider id | What it is | Class | Evidence and notes |
|---|---|---|---|
| `openai` | OpenAI API | API key | seen in lane template seats |
| `anthropic` | Anthropic API, pay per token | API key | not seen in lane templates; add when a company key exists (unverified) |
| `xai` | xAI API | API key | not seen; unverified |
| `deepseek` | DeepSeek API | API key | not seen; unverified |
| `cheaperinference` | reseller endpoint (claude-sonnet-5, kimi-k3 seats) | API key | seen in lane template seats |
| `openrouter` | aggregator; only `:free` and `ox-alpha` seats on capacity lanes | API key, mixed cost | runbook inventory |
| `nous` (`nous-research`) | NousResearch endpoint | API key, free tier | runbook; combo alias `nous` maps to connection `nous-research` |
| `nvidia` | NVIDIA NIM | API key, free credits | runbook inventory |
| `gemini` | Google Gemini API | API key | runbook inventory |
| `alibaba`, `bailian-coding-plan` | Alibaba DashScope and coding plan | API key (plan) | runbook; headed most combos in 2026-08, concentration risk |
| `huggingface`, `nebius` | HF Inference Providers, Nebius AI Studio | API key | runbook; tail seats only |
| `claude` | Claude Max through Claude Code sign-in | subscription seat | connection existed with `is_active=0` (deliberate) on 2026-08-24; enabling it is the 2026-10-02 decision |
| `codex`, `cx` | ChatGPT Codex sign-in | subscription seat | `cx/gpt-5.6-terra-max` seated in lane templates |
| `grok` | SuperGrok through Grok CLI | subscription seat | hard-excluded from fleet combos as of 2026-08; 2026-10-02 decision allows seating |
| `cursor` | Cursor gateway session | subscription seat | broadest tail seat in 2026-08 |
| `antigravity`, `agy` | Google Antigravity | subscription seat | seen in templates; connection id mismatch (`antigravity` vs `agy`) noted in runbook |
| `command-code`, `cmd` | Command Code plan (`usd100_10x`) | subscription (plan key) | inactive after 504s in 2026-08; self-heals when healthy |
| `cc` | prefix seen as `cc/claude-opus-4-7` | likely subscription | mapping unverified (possibly a Claude Code seat) |
| `gc` | prefix seen in templates | unknown | unverified |
| `kimi-web`, `pplx-web`, `perplexity-web` | web-session seats | session (subscription-like) | terms unverified |

## Wing defaults (starting points, tune after two weeks of call logs)

| Wing | Default combo | Also useful | Why |
|---|---|---|---|
| all wings | `noesis-orchestrator` | `noesis-fast` for quick turns | the standard coordinator lane; what Claude Code resolves to by default |
| coding | `noesis-build` | `noesis-review`, `noesis-execute` (batch workers only, with a worktree claim) | long multi-file work |
| marketing | `noesis-fast` for drafting | `noesis-write`, `noesis-write-critique`, `noesis-research` | capacity lane for volume, writing lanes for finals |
| design | `noesis-plan` for reviews | `noesis-vision`, `noesis-media`, `noesis-creative` | structured critique; vision lanes for image work |

Phase map shared by every seat: Observe/Think/Learn `noesis-observe`, Plan `noesis-plan`, Build
`noesis-build`, Execute `noesis-execute`, Verify `noesis-verify`. The Grok CLI blocks written by
`gateway_client.py` expose `te-orchestrator`, `te-build`, `te-fast`, `te-plan`, each pointing at the
matching `noesis-*` combo (the gateway only serves `noesis-*` names).

## How a wing requests a new provider

1. Open an issue in this repo labelled `fleet-provider` with: provider name, class (API key or
   subscription), who pays, which wing needs it, which combos should seat it, expected monthly spend,
   and a link to the provider's terms.
2. The gateway operator connects it on the Coding Mac, seats it in the lane template, attaches the
   `sync-provider-fleet.py` dry-run receipt to the issue, then applies. Never hand-edit combos.
3. Send a PR that adds the row to this file. The kit's `host/lane-templates-from-live.json` is a
   snapshot for handoff; the live file on the Coding Mac is the authority.
