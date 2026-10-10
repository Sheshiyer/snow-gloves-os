// What scripts/sg_mods.py snapshot prints (schema snowgloves.mods-snapshot.v1), trimmed to what the band reads.
export type Snapshot = {
  schema: 'snowgloves.mods-snapshot.v1'
  data_root: string
  data_root_source: 'flag' | 'env' | 'code-fallback'
  tenant: string | null
  tenant_source: 'flag' | 'project-match' | 'none'
  tenants: string[]
  approvals: { pending_total: number; by_tenant: Record<string, number> }
  walk: { verdict: string; events: number; loops: number } | null
  isa: { checked: number; total: number } | null
  endpoints: { hermes: string; omniroute: string }
  warnings: string[]
}

// null until probed, then whether /healthz answered ok
export type Health = { hermes: boolean | null; omniroute: boolean | null }

// The Temperance rail, read from ~/.claude/MEMORY/STATE/rail/<session>.ui.json (schema temperance.rail-ui.v1)
export type RailUi = { rail: string; manifest: string; updatedAt: string }

declare module 'claude-code' {
  interface PluginState {
    'sg-rail': {
      snapshot: Snapshot | null
      health: Health
      rail: RailUi | null
      error: string | null
      isHidden: boolean
    }
  }
}
