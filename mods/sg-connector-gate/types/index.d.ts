// What scripts/sg_mods.py gate-table prints (schema snowgloves.mods-gate.v1).
export type GateServer = {
  category: string
  disposition: 'add' | 'pointer' | 'hold' | 'refuse'
  risk: 'low' | 'medium' | 'high'
  approval: 'yes' | 'no'
  enabled: boolean
  needs_approval: boolean
}

export type GateTable = {
  schema: 'snowgloves.mods-gate.v1'
  tenant: string
  data_root: string
  ttl_hours: number
  managed: string[]
  servers: Record<string, GateServer>
  grants: { connector: string; capability: string; id: string; decided_at: number }[]
  pending: { connector: string; capability: string; id: string }[]
}

// pass: let the call go on. deny: refuse it with a reason Claude reads. approve: queue a ticket, then refuse.
export type GateDecision =
  | { kind: 'pass' }
  | { kind: 'deny'; reason: string }
  | { kind: 'approve'; connector: string; capability: string }
