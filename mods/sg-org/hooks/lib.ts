// Pure helpers for sg-org. No $ here.
import type { OrgAgent } from '../types'

export const TYPE_PREFIX = 'sg-org:'

export function platformRootFrom(pluginRoot: string): string {
  return pluginRoot.split('/').slice(0, -2).join('/')
}

export type Table = { agents: OrgAgent[]; restricted: boolean; tenant: string | null }

export function tableFrom(stdout: string): Table | null {
  try {
    const data = JSON.parse(stdout)
    if (!data || !Array.isArray(data.agents)) return null
    return { agents: data.agents, restricted: data.restricted === true, tenant: typeof data.tenant === 'string' ? data.tenant : null }
  } catch {
    return null
  }
}

// What $.agent.register takes for one agent.
export function specOf(a: OrgAgent) {
  return {
    name: a.slug,
    description: a.role + '. ' + a.description,
    prompt: a.prompt,
    tools: a.tools,
  }
}

// "sentinel=noesis-verify, cto=noesis-build" -> { sentinel: 'noesis-verify', cto: 'noesis-build' }
export function parseRoleCombos(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const part of text.split(',')) {
    const [role, combo] = part.split('=').map((s) => s.trim())
    if (role && combo) out[role] = combo
  }
  return out
}

// ANTHROPIC_BASE_URL points at the OmniRoute gateway: its local port, or a gateway host the fleet names.
export function isOmniRoute(baseUrl: string | undefined): boolean {
  return !!baseUrl && /:20128\b|omniroute|\/\/gw\./i.test(baseUrl)
}

// Whether the model is offered an sg-org type: always, unless the tenant lists agents and this one is not among them.
export function isOffered(agents: OrgAgent[], restricted: boolean, type: string): boolean {
  const slug = type.startsWith(TYPE_PREFIX) ? type.slice(TYPE_PREFIX.length) : type
  const found = agents.find((a) => a.slug === slug)
  if (!found) return true
  return !restricted || found.enabled
}

export function laneLines(a: OrgAgent): string[] {
  const hooks = a.hooks.map((h) => h.id).join(', ') || 'none'
  return [
    a.slug + '  ' + a.role + (a.enabled ? '' : '  (not enabled for this tenant)'),
    '  skills: ' + (a.default_skills.join(', ') || 'none') + '   hooks: ' + hooks,
    '  tools: ' + a.tools.join(', ') + (a.readonly ? ' (read only)' : '') + '   escalates to: ' + (a.escalates_to || 'nobody') + '   heartbeat: stale',
  ]
}

export function orgText(agents: OrgAgent[], tenant: string | null, error: string | null): string {
  if (error) return 'Org unavailable: ' + error
  return ['Org' + (tenant ? ' for ' + tenant : ''), ...agents.flatMap(laneLines)].join('\n')
}
