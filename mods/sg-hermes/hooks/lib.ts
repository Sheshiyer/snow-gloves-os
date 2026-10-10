// Pure helpers for sg-hermes. No $ here.
import type { HermesEvent, Replay, Route } from '../types'

export const DEFAULT_URL = 'http://127.0.0.1:4100'
export const KEEP = 200

export function platformRootFrom(pluginRoot: string): string {
  return pluginRoot.split('/').slice(0, -2).join('/')
}

export function trimUrl(url: string): string {
  return url.replace(/\/+$/, '')
}

// The Hermes endpoint: the option, else the platform snapshot's, else the default.
export function hermesUrl(option: string, snapshotStdout: string | null): string {
  if (option.trim()) return trimUrl(option.trim())
  try {
    const url = JSON.parse(snapshotStdout || '{}')?.endpoints?.hermes
    if (typeof url === 'string' && /^https?:\/\//.test(url)) return trimUrl(url)
  } catch {
    // fall through to the default
  }
  return DEFAULT_URL
}

export function eventsFrom(text: string): HermesEvent[] | null {
  try {
    const data = JSON.parse(text)
    if (!data || !Array.isArray(data.events)) return null
    return data.events.filter((x: unknown) => x && typeof (x as HermesEvent).ts === 'string')
  } catch {
    return null
  }
}

// Newest KEEP events, oldest first, no repeats of a timestamp already held.
export function mergeEvents(old: HermesEvent[], fresh: HermesEvent[]): HermesEvent[] {
  const seen = new Set(old.map((e) => e.ts + e.kind))
  const added = fresh.filter((e) => !seen.has(e.ts + e.kind))
  return [...old, ...added].slice(-KEEP)
}

export function newestTs(events: HermesEvent[]): string | null {
  return events.length ? events[events.length - 1].ts : null
}

export function routesFrom(text: string): Route[] | null {
  try {
    const data = JSON.parse(text)
    return Array.isArray(data?.routing) ? data.routing : null
  } catch {
    return null
  }
}

export function replayFrom(text: string): Replay[] | null {
  try {
    const data = JSON.parse(text)
    return Array.isArray(data) ? data : null
  } catch {
    return null
  }
}

export function routeLine(r: Route): string {
  return r.agent + ' via ' + r.hook + ' (' + r.matched_glob + ')' + (r.skills.length ? ' skills: ' + r.skills.join(', ') : '')
}

export function eventLine(e: HermesEvent): string {
  const task = (e.task || (e.event as { payload?: unknown } | undefined)?.payload || {}) as { title?: string }
  const routing = Array.isArray(e.routing) ? (e.routing as Route[]).map((r) => r.agent).join('+') : ''
  const detail = e.kind === 'claude.turn' || (e.event as { kind?: string } | undefined)?.kind === 'claude.turn' ? 'claude turn' : task.title || ''
  return e.ts.slice(11, 19) + '  ' + e.kind + (detail ? '  ' + detail : '') + (routing ? '  -> ' + routing : '')
}

export function replayLine(r: Replay): string {
  const names = (rs: Route[]) => rs.map((x) => x.agent).join('+') || 'none'
  return r.ts.slice(11, 19) + '  ' + (r.task?.title || '(untitled)') + '  ' + names(r.before) + ' -> ' + names(r.after)
}

export function turnEvent(session: string, durationMs: number, usage: unknown, tenant: string) {
  return { channel: 'claude', event: { kind: 'claude.turn', session, durationMs, usage: usage ?? null, tenant } }
}
