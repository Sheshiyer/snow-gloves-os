# Recovery worker review

Source checkpoint reviewed: `8bf8b2b`. Baseline freshly reproduced: 138 tests.

The original CLI retry reached its 12-turn cap after creating two draft files.
It did not finish passing focused tests. Its test indexes the toolchain layer as
the runtime layer, and its plan digest includes changing disk evidence. It lacks
the confirmed apply/resume/rollback pilot contract. Do not integrate this draft.

Controller rerun: CLI **20 passed, 1 failed**. Policy **42 passed** before the
adversarial digest probe; approval verification remains optional in source.

The original policy retry returned success and a claim of 42 passing tests.
The review found optional approval-verifier enforcement and concatenated digest
inputs that need adversarial review before acceptance. These source files remain
in `/tmp/snowgloves-bootstrap-policy`; no production authorization boundary uses
them. They are outside the confirmed one-mini local pilot scope and are not
integrated in this change.

Controller probe reproduced the digest flaw: `digest_content({'a':'xb=y','c':'z'})`
equals `digest_content({'a':'x','b':'yc=z'})`. The unequal payloads concatenate to
the same unhashed byte sequence. Passing draft tests do not accept this boundary.

Replacement production of the pilot uses explicit file ownership and a single
`.planning/PILOT-CONTRACT.md`. The pinned rail is Command Code,
`poolside/laguna-s-2.1-free`, with 12 turns and a 600-second wall-clock bound.
Standalone isolated output checkouts avoid inherited planning-context loops.
Direct Command Code receipts prove the selected client/model and tool calls;
they do not claim OmniRoute gateway attribution.

All acceptance happens after reviewing files and running controller tests.

## Late repair receipts — 30 September pickup

Direct Command Code / poolside/laguna-s-2.1-free CLI repair completed;
controller rerun: 22 focused tests passed. The draft still lacks the selected
apply/resume/rollback pilot contract and is not integrated.

Policy repair reached its 14-turn cap. Controller rerun: 42 tests passed,
but source still makes approval verification optional and does not authorize
the approver capability at the requested scope. Canonical JSON digest repairs
are present, but passing old tests does not certify the unfinished boundary.
No policy implementation accepted.

The newer pilot handoff wins: no further worker dispatch while its explicit
routing decision remains pending. Original repair processes have exited.
