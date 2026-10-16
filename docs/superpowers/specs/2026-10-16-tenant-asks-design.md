# Tenant asks: the founder's queue inside the town

Agreed with the founder on 2026-10-16. Instance facts (tenant names, counts, business details) live in the private ops checkout, never here.

## Intent

The fleet Macs sit idle because every tenant is waiting on founder input that has no place to land. Make every kind of founder input a first-class **ask**, show asks inside the existing town UI (not a separate page), and let agents propose while the founder decides: agents work → asks → founder answers → agents continue.

## Kinds of ask

| Kind | Founder action | Owning crew role | Derived from (private data) |
|---|---|---|---|
| `fact` | type a value, or accept/reject an agent's proposed value | librarian | `FILL:` lines in `tenants/<t>/context/*.md` (not `open-questions.md`, which repeats them) |
| `decision` | yes / no | chief-of-staff | cross-brand flows in the portfolio proposal whose status is not approved and which name the tenant |
| `connect` | sign in / bind, or mark "not needed" | dispatcher | sources in `sources.yaml` with `admitted: false`; enabled `mcp`/`connector` modules (auth is never verified by configuration) |
| `website` | type or confirm the brand domain/site facts | interpreter | `brand.domain` still `FILL` in `MANIFEST.yaml` |
| `brand` | accept or request a Meristem brand handoff | interpreter | tenant has no registered source whose id contains `meristem` |

Each ask has a stable id (`sha256("<tenant>|<kind>|<key>")[:32]`), so re-deriving after data changes keeps answers attached. An ask whose source disappears (the FILL was filled) is no longer derived and drops out.

## Authority and storage

- The fleet coordinator on Coding 01 is the only writer. Asks join its existing approvals mechanism: listing needs `read`; answering needs `approve` (founder-only today).
- Answers are stored in the coordinator database and appended to `tenants/<t>/asks/answers.jsonl` in the private data root (append-only, symlink-safe). The journal is the durable record; agents read it to apply answers.
- Agent proposals arrive as task artifacts and are imported to `tenants/<t>/asks/proposed.jsonl`; a `fact` ask with a proposal is answered Yes/No instead of typed.

## In the town

- Brand markers by the tenant-vault building show the tenant's open-ask count.
- The crew strip shows how many asks each role holds, replacing "No active evidence" when asks exist.
- Clicking a crew portrait or a brand marker opens the ask stack (filtered by role or tenant) with real Yes/No buttons and input fields.
- The tenant card in Neighborhoods gets a "Waiting on you" section with the same stack.
- Asks need the operator token; they appear once the Hermes board is connected and clear on disconnect.

## Kickoff

- Admit each tenant as a coordinator project: read-only, `codex` runtime, no write, no fanout.
- Submit one read-only research task per tenant: propose values for its open `fact` asks from its own context, public sources and Meristem outputs, returning JSON proposals. Imported proposals become Yes/No asks.

## Non-goals

- No new standalone page, and no new auth system.
- No write access for workers, and no approval-required module enabled by this work.
- Answers do not edit context files automatically; applying them is a later agent task that reads the journal.

## Constraints

- Follow the existing fail-closed style: bounded parsers, size caps, a sensitive-value filter, and no secrets in any ask or answer.
- Answer text ≤ 500 characters; ≤ 400 asks per tenant; ask titles ≤ 160 characters.
