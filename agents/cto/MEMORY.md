# Memory — Chief Technology Agent

## Scope
- Tenant-scoped only. No cross-tenant reads.
- Stored as append-only journal at `tenants/<tenant>/agents/cto/memory.jsonl`.

## Schema (per entry)
```json
{"ts": "ISO8601", "task_id": "...", "input": {...}, "decision": {...}, "outcome": "...", "links": ["audit:..."]}
```

## Retention
- Hot: last 90 days
- Cold: archived to `_audit/cold/cto/`

## Access rules
- Read by: this agent, sentinel
- Write by: this agent, dispatcher (on completion)
