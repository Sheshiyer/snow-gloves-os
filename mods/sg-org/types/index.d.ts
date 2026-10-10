// One of the seven agents as scripts/sg_mods.py agents describes it.
export type OrgAgent = {
  slug: string
  role: string
  layer: string
  description: string
  prompt: string
  tools: string[]
  readonly: boolean
  default_skills: string[]
  hooks: { id: string; globs: string[] }[]
  escalates_to: string | null
  enabled: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'sg-org': {
      agents: OrgAgent[]
      restricted: boolean
      tenant: string | null
      error: string | null
    }
  }
}
