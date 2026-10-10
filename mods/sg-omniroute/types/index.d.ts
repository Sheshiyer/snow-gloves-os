// One model request of a turn, from turn.step's result.
export type Row = {
  turnId: string
  index: number
  agent: string
  model: string
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
}
// One OmniRoute combo as scripts/sg_mods.py combos lists it.
export type Combo = { name: string; strategy: string; members: string[] }

declare module 'claude-code' {
  interface PluginState {
    'sg-omniroute': {
      rows: Row[]
      combos: Combo[]
      comboError: string | null
      meter: string | null
    }
  }
}
