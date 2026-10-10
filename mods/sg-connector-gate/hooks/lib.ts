// Pure rules for sg-connector-gate, mirroring skills/connector-gate/SKILL.md. No mods API calls here.
import type { GateDecision, GateTable } from '../types'

export const GATE_SCHEMA = 'snowgloves.mods-gate.v1'

export function platformRootFrom(pluginRoot: string): string {
  const parts = pluginRoot.replace(/\/+$/, '').split('/')
  return parts.slice(0, -2).join('/') || '/'
}

export function asGateTable(text: string): GateTable | null {
  try {
    const value = JSON.parse(text)
    return value && value.schema === GATE_SCHEMA && typeof value.servers === 'object' ? value : null
  } catch {
    return null
  }
}

// mcp__<server>__<tool>; the adapter keys .mcp.json by card id, so <server> is the card id
export function splitTool(tool: string): { server: string; name: string } | null {
  if (!tool.startsWith('mcp__')) return null
  const rest = tool.slice('mcp__'.length)
  const cut = rest.indexOf('__')
  if (cut <= 0) return null
  return { server: rest.slice(0, cut), name: rest.slice(cut + 2) }
}

export function isManaged(table: GateTable | null, tool: string): boolean {
  const parts = splitTool(tool)
  return table !== null && parts !== null && parts.server in table.servers
}

export function decide(table: GateTable | null, tool: string): GateDecision {
  const parts = splitTool(tool)
  if (!table || !parts) return { kind: 'pass' }
  const server = table.servers[parts.server]
  // Servers the catalog doesn't list are not Snow Gloves'. They go on untouched, so the
  // settings PreToolUse hooks that guard them (erp-read-only.py) still run.
  if (!server) return { kind: 'pass' }
  const id = parts.server
  if (server.disposition === 'hold') {
    return {
      kind: 'deny',
      reason: `${id} is on hold in the Snow Gloves catalog: it waits on a founder pick and a review, so it can't be called yet.`,
    }
  }
  if (server.disposition === 'refuse') {
    return { kind: 'deny', reason: `${id} is refused in the Snow Gloves catalog, so Snow Gloves will not run it.` }
  }
  if (!server.enabled) {
    return {
      kind: 'deny',
      reason:
        `${id} is not enabled for tenant ${table.tenant}. ` +
        `Ask the user whether to enable it with: python3 scripts/onboard.py --tenant ${table.tenant} --enable ${id}`,
    }
  }
  if (server.needs_approval) {
    const granted = table.grants.some((g) => g.connector === id && g.capability === parts.name)
    if (!granted) return { kind: 'approve', connector: id, capability: parts.name }
  }
  return { kind: 'pass' }
}

export function approvalReason(tool: string, tenant: string, ticket: string): string {
  return (
    `${tool} needs founder approval for tenant ${tenant}. Ticket ${ticket} is queued. ` +
    'Ask the user to approve it in /approvals, then retry the call.'
  )
}

export function statusText(table: GateTable | null, mode: string, error: string | null): string {
  // Claude Code prints the plugin's name in front of a command's text
  if (!table) return 'observing only (' + (error || 'no tenant') + '). Every MCP call goes on.'
  const lines = [`${mode} for tenant ${table.tenant}`]
  for (const id of table.managed) {
    const s = table.servers[id]
    const state =
      s.disposition === 'hold' || s.disposition === 'refuse'
        ? s.disposition
        : !s.enabled
          ? 'not enabled'
          : s.needs_approval
            ? 'enabled, approval per tool'
            : 'enabled'
    lines.push(`  ${id}: ${state}`)
  }
  if (table.grants.length > 0) {
    lines.push('approved: ' + table.grants.map((g) => g.connector + '.' + g.capability).join(', '))
  }
  if (table.pending.length > 0) {
    lines.push('waiting: ' + table.pending.map((p) => p.connector + '.' + p.capability + ' ' + p.id).join(', '))
  }
  return lines.join('\n')
}
