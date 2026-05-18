# G-Stack Connector Fabric (Composio-like)

## Responsibilities

1. Connector auth lifecycle (OAuth/API keys)
2. Scope governance per tenant
3. Capability normalization (`read_bookings`, `create_invoice`, etc.)
4. Webhook signature validation + ingestion
5. Health checks + permission drift alerts

## Security Model

- Least-privilege scopes
- Rotatable credentials
- Tenant-bound connector identities
- Signed event envelopes into orchestration

## Integration Contract

Input:
- Connector event payload
- Tenant ID
- Connector capability

Output:
- Normalized event envelope
- Correlation ID
- Security metadata
