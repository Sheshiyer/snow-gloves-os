# Agent Relationships — Interpretation Engine

## Upstream
- Hermes channel: `snowgloves.events.v1`
- Chief of Staff (skill routing)

## Peers
- ceo, cto, chief-of-staff, librarian, interpreter, dispatcher, sentinel

## Downstream
- Paperclip lane: `interpreter`
- Audit sink: `_audit/trace.log`

## Contract
- Inputs: routed task envelope (title, tags, brief, tenant, policy)
- Outputs: interpreted action, approval request, or escalation
- SLA: respond within 1 heartbeat (5 min) or escalate
