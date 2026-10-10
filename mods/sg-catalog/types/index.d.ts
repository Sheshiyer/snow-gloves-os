// One catalog card as scripts/sg_mods.py catalog lists it (no body).
export type Card = {
  id: string
  name: string
  category: string
  kind: string
  disposition: string
  risk: string
  approval: string
  agents: string[]
  summary: string
  enableable: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'sg-catalog': {
      cards: Card[]
      enabled: string[]
      tenant: string | null
      category: string
      disposition: string
      error: string | null
      note: string | null
    }
  }
}
