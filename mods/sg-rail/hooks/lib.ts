// Pure helpers for sg-rail. Nothing here calls the mods API, so tests can import them directly.
import type { Health, RailUi, Snapshot } from '../types'

export const SNAPSHOT_SCHEMA = 'snowgloves.mods-snapshot.v1'
export const RAIL_UI_SCHEMA = 'temperance.rail-ui.v1'

// mods/<name> sits two folders under the platform checkout
export function platformRootFrom(pluginRoot: string): string {
  const parts = pluginRoot.replace(/\/+$/, '').split('/')
  return parts.slice(0, -2).join('/') || '/'
}

export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

export function asSnapshot(value: unknown): Snapshot | null {
  if (!value || typeof value !== 'object') return null
  const snap = value as Snapshot
  return snap.schema === SNAPSHOT_SCHEMA && typeof snap.endpoints === 'object' ? snap : null
}

export function asRailUi(value: unknown): RailUi | null {
  if (!value || typeof value !== 'object') return null
  const ui = value as Record<string, unknown>
  if (ui.schema !== RAIL_UI_SCHEMA) return null
  return {
    rail: typeof ui.rail === 'string' ? ui.rail : '',
    manifest: typeof ui.manifest_runtime === 'string' ? ui.manifest_runtime : '',
    updatedAt: typeof ui.updated_at === 'string' ? ui.updated_at : '',
  }
}

function field(text: string, name: string): string | null {
  const match = new RegExp('^\\s*·\\s*' + name + '\\s+(.+?)\\s*$', 'm').exec(text)
  return match ? match[1] : null
}

// "♄ RAIL · NIGREDO · OBSERVE · 1/7" plus mode, combo and head, on one line
export function railLine(text: string): string | null {
  const header = /RAIL\s*·\s*(.+?)\s*$/m.exec(text)
  if (!header) return null
  const bits = ['♄ ' + header[1]]
  const mode = field(text, 'mode')
  const combo = field(text, 'combo')
  const head = field(text, 'head')
  if (mode) bits.push(mode)
  if (combo) bits.push('combo ' + combo)
  if (head) bits.push('head ' + head)
  return bits.join(' · ')
}

// "☿ MANIFEST · OFFLINE" plus the omniroute row, on one line
export function manifestLine(text: string): string | null {
  const header = /MANIFEST\s*·\s*(\S+)/.exec(text)
  if (!header) return null
  const omniroute = field(text, 'omniroute')
  const route = omniroute ? ' · omniroute ' + omniroute.split(' ')[0] : ''
  return '☿ manifest ' + header[1].toLowerCase() + route
}

export function dot(ok: boolean | null): string {
  return ok === null ? '·' : ok ? '●' : '○'
}

export function dataLabel(snap: Snapshot): string {
  if (snap.data_root_source === 'code-fallback') return 'fixtures'
  return snap.data_root.split('/').filter(Boolean).pop() || snap.data_root
}

export function fit(text: string, columns: number): string {
  if (!(columns > 1) || text.length <= columns) return text
  return text.slice(0, columns - 1) + '…'
}

export function statusLine(snap: Snapshot, health: Health): string {
  const bits = [
    'SG ' + (snap.tenant ?? 'no tenant'),
    'data ' + dataLabel(snap),
    'hermes ' + dot(health.hermes),
    'omniroute ' + dot(health.omniroute),
    'approvals ' + snap.approvals.pending_total,
  ]
  if (snap.walk) bits.push('walk ' + snap.walk.verdict)
  if (snap.isa) bits.push('ISA ' + snap.isa.checked + '/' + snap.isa.total)
  return bits.join(' · ')
}

export function bandLines(
  snap: Snapshot | null,
  health: Health,
  rail: RailUi | null,
  error: string | null,
  columns: number,
): string[] {
  const lines: string[] = []
  if (snap) lines.push(statusLine(snap, health))
  else if (error) lines.push('SG snapshot failed: ' + error)
  const railText = rail ? railLine(rail.rail) : null
  const manifestText = rail ? manifestLine(rail.manifest) : null
  if (railText) lines.push(railText)
  if (manifestText) lines.push(manifestText)
  return lines.map((line) => fit(line, columns))
}

export function summaryText(
  snap: Snapshot | null,
  health: Health,
  rail: RailUi | null,
  error: string | null,
): string {
  if (!snap) return 'Snapshot unavailable' + (error ? ': ' + error : '')
  const lines = [
    statusLine(snap, health),
    'tenant: ' + (snap.tenant ?? 'none') + ' (' + snap.tenant_source + ')',
    'data root: ' + snap.data_root + ' (' + snap.data_root_source + ')',
    'hermes: ' + snap.endpoints.hermes + ' ' + dot(health.hermes),
    'omniroute: ' + snap.endpoints.omniroute + ' ' + dot(health.omniroute),
  ]
  const byTenant = Object.entries(snap.approvals.by_tenant)
  if (byTenant.length > 0) lines.push('pending approvals: ' + byTenant.map(([t, n]) => t + ' ' + n).join(', '))
  const railText = rail ? railLine(rail.rail) : null
  if (railText) lines.push(railText)
  for (const warning of snap.warnings) lines.push('warning: ' + warning)
  return lines.join('\n')
}
