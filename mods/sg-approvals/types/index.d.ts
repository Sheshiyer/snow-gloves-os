// One pending ticket as scripts/sg_mods.py snapshot lists it. Payload values never leave Python, only keys.
export type Ticket = {
  tenant: string
  id: string
  connector: string
  capability: string
  kind: string
  risk: string
  created_at: number | null
  payload_keys: string[]
}

declare module 'claude-code' {
  interface PluginState {
    'sg-approvals': {
      tickets: Ticket[]
      error: string | null
      note: string | null
    }
  }
}
