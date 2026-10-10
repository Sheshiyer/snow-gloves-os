// Pure helpers for sg-omniroute. No $ here.
import type { Combo, Row } from '../types'

export const KEEP = 200

export function platformRootFrom(pluginRoot: string): string {
  return pluginRoot.split('/').slice(0, -2).join('/')
}

type Usage = { model?: string; input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number }

// A ledger row from a finished step; null when the step made no request.
export function rowOf(turnId: string, index: number, agentId: string | undefined, fallbackModel: string, usage: Usage | null | undefined): Row | null {
  if (!usage) return null
  return {
    turnId,
    index,
    agent: agentId || 'main',
    model: usage.model || fallbackModel,
    input: usage.input_tokens || 0,
    output: usage.output_tokens || 0,
    cacheRead: usage.cache_read_input_tokens || 0,
    cacheWrite: usage.cache_creation_input_tokens || 0,
  }
}

export function addRow(rows: Row[], row: Row): Row[] {
  return [...rows, row].slice(-KEEP)
}

// Share of the prompt the cache served: read / (read + written + uncached).
export function cacheRatio(rows: Row[]): number | null {
  const read = rows.reduce((n, r) => n + r.cacheRead, 0)
  const all = rows.reduce((n, r) => n + r.cacheRead + r.cacheWrite + r.input, 0)
  return all > 0 ? read / all : null
}

export type ModelTotal = { model: string; requests: number; input: number; output: number; cacheRead: number; cacheWrite: number }

export function totalsByModel(rows: Row[]): ModelTotal[] {
  const by = new Map<string, ModelTotal>()
  for (const r of rows) {
    const t = by.get(r.model) || { model: r.model, requests: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }
    t.requests += 1
    t.input += r.input
    t.output += r.output
    t.cacheRead += r.cacheRead
    t.cacheWrite += r.cacheWrite
    by.set(r.model, t)
  }
  return [...by.values()].sort((a, b) => b.requests - a.requests)
}

export const kilo = (n: number) => (n >= 10_000 ? Math.round(n / 1000) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n))

export function rowLine(r: Row): string {
  return r.agent + '  ' + r.model + '  in ' + kilo(r.input) + '  out ' + kilo(r.output) + '  cache r' + kilo(r.cacheRead) + ' w' + kilo(r.cacheWrite)
}

export function totalLine(t: ModelTotal): string {
  return t.model + '  ' + t.requests + ' req  in ' + kilo(t.input) + '  out ' + kilo(t.output) + '  cache r' + kilo(t.cacheRead) + ' w' + kilo(t.cacheWrite)
}

type RateLimit = { kind: string; percentUsed: number }
export function meterText(usage: { context?: { percent?: number }; rateLimits?: RateLimit[]; cost?: { usd: number } } | null, rows: Row[]): string | null {
  if (!usage) return null
  const parts: string[] = []
  if (typeof usage.context?.percent === 'number') parts.push('ctx ' + Math.round(usage.context.percent) + '%')
  for (const l of usage.rateLimits || []) parts.push(l.kind + ' ' + Math.round(l.percentUsed) + '%')
  const ratio = cacheRatio(rows)
  if (ratio !== null) parts.push('cache ' + Math.round(ratio * 100) + '%')
  if (typeof usage.cost?.usd === 'number') parts.push('$' + usage.cost.usd.toFixed(2))
  return parts.length ? 'omniroute · ' + parts.join(' · ') : null
}

export function combosFrom(stdout: string): Combo[] | null {
  try {
    const data = JSON.parse(stdout)
    return Array.isArray(data?.combos) ? data.combos : null
  } catch {
    return null
  }
}

export function comboLine(c: Combo): string {
  return c.name + '  ' + c.strategy + '  ' + c.members.length + ' members: ' + c.members.join(', ')
}

export function ledgerText(rows: Row[]): string {
  if (!rows.length) return 'No requests recorded yet.'
  const ratio = cacheRatio(rows)
  return [
    rows.length + ' requests' + (ratio === null ? '' : ', cache served ' + Math.round(ratio * 100) + '% of the prompt'),
    ...totalsByModel(rows).map(totalLine),
  ].join('\n')
}
