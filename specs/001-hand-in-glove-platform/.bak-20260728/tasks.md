# Tasks: Hand-In-Glove Platform Core

## Foundation

- [ ] T001 Define tenant and connector schemas
- [ ] T002 Define interpreted-context schema
- [ ] T003 Define workflow intent + approval schemas
- [ ] T004 Add audit trace schema and storage model

## Connector Fabric (G-Stack)

- [ ] T010 Implement connector binding registry
- [ ] T011 Implement capability catalog per connector
- [ ] T012 Implement token refresh + scope validation hooks
- [ ] T013 Implement connector health and permission checks

## Knowledge + Embedding

- [ ] T020 Implement wiki/doc ingestion adapters
- [ ] T021 Implement chunking + metadata enrichment
- [ ] T022 Implement embedding provider abstraction (NVIDIA-first)
- [ ] T023 Implement vector retrieval API with tenant filtering

## Interpretation Layer

- [ ] T030 Implement entity extraction/resolution pipeline
- [ ] T031 Implement policy tagger and risk classifier
- [ ] T032 Implement confidence scoring and fallback behavior
- [ ] T033 Implement interpreted context query endpoint

## Hermes + Paperclip Orchestration

- [ ] T040 Implement event envelope translation to Hermes
- [ ] T041 Implement Paperclip task creation/update sync
- [ ] T042 Implement approval-gate routing for high-risk actions
- [ ] T043 Implement escalation policies and owner resolution

## Validation + Observability

- [ ] T050 Add end-to-end trace for one workflow (ingest → interpret → execute)
- [ ] T051 Add metrics dashboard for routing, failures, approvals
- [ ] T052 Add tenant isolation test suite

## Domain Pack Starter (Hospitality)

- [ ] T060 Add hospitality connector pack template
- [ ] T061 Add bookings/ops/finance/hr/legal workflow templates
- [ ] T062 Add sample Co-property-style onboarding config
