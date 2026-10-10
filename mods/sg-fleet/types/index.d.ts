// One doctor check as scripts/fleet/doctor.py --json lists it.
export type Check = { name: string; ok: boolean; detail: string; critical: boolean }
// One CLI surface as scripts/fleet/gateway_client.py status prints it.
export type Surface = { name: string; fleet: boolean; base: string }

declare module 'claude-code' {
  interface PluginState {
    'sg-fleet': {
      checks: Check[]
      surfaces: Surface[]
      error: string | null
      checkedAt: number | null
    }
  }
}
