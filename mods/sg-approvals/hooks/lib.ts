// Pure helpers for sg-approvals. No mods API calls here.
import type { Ticket } from '../types'

export const SNAPSHOT_SCHEMA = 'snowgloves.mods-snapshot.v1'

export function platformRootFrom(pluginRoot: string): string {
  const parts = pluginRoot.replace(/\/+$/, '').split('/')
  return parts.slice(0, -2).join('/') || '/'
}

export function ticketsFrom(text: string): Ticket[] | null {
  try {
    const value = JSON.parse(text)
    if (!value || value.schema !== SNAPSHOT_SCHEMA || !value.approvals) return null
    return Array.isArray(value.approvals.items) ? value.approvals.items : []
  } catch {
    return null
  }
}

export function ageOf(createdAt: number | null, nowSeconds: number): string {
  if (createdAt === null) return '?'
  const seconds = Math.max(0, nowSeconds - createdAt)
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm'
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h'
  return Math.floor(seconds / 86400) + 'd'
}

export function ticketLine(t: Ticket, nowSeconds: number): string {
  // G-Stack capability ids already start with the connector, as in gmail.send_message
  const prefixed = !t.connector || t.capability.startsWith(t.connector + '.')
  const what = t.capability ? (prefixed ? '' : t.connector + '.') + t.capability : t.kind || t.connector || '?'
  const bits = [t.tenant, what, 'risk ' + (t.risk || '?'), ageOf(t.created_at, nowSeconds)]
  if (t.payload_keys.length > 0) bits.push('payload: ' + t.payload_keys.join(', '))
  return bits.join(' · ')
}

// Ids that appeared since the last look; the first look only sets the baseline
export function newIds(seen: Set<string> | null, tickets: Ticket[]): string[] {
  if (seen === null) return []
  return tickets.map((t) => t.id).filter((id) => !seen.has(id))
}

export function isHighRisk(t: Ticket): boolean {
  return t.risk === 'high'
}
