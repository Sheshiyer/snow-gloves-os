// Pure helpers for sg-fleet. No $ here.
import type { Check, Surface } from '../types'

export function platformRootFrom(pluginRoot: string): string {
  return pluginRoot.split('/').slice(0, -2).join('/')
}

export function checksFrom(stdout: string): Check[] | null {
  let data: unknown
  try {
    data = JSON.parse(stdout)
  } catch {
    return null
  }
  if (!Array.isArray(data)) return null
  const out: Check[] = []
  for (const item of data) {
    if (!item || typeof item !== 'object' || typeof (item as Check).name !== 'string') return null
    const c = item as Check
    out.push({ name: c.name, ok: c.ok === true, detail: String(c.detail ?? ''), critical: c.critical === true })
  }
  return out
}

// "  claude    FLEET base=http://x  file=/path" lines from gateway_client.py status
export function surfacesFrom(stdout: string): Surface[] {
  const out: Surface[] = []
  for (const line of stdout.split('\n')) {
    const m = /^\s{2}(\S+)\s+(NOT-FLEET|FLEET)\s+base=(\S+)/.exec(line)
    if (m) out.push({ name: m[1], fleet: m[2] === 'FLEET', base: m[3] })
  }
  return out
}

// Critical checks that were green (or unseen) before and are red now. The first look reports none.
export function newlyRed(before: Check[] | null, after: Check[]): string[] {
  if (before === null) return []
  const was = new Map(before.map((c) => [c.name, c.ok]))
  return after.filter((c) => c.critical && !c.ok && was.get(c.name) !== false).map((c) => c.name)
}

export function summary(checks: Check[]): string {
  const bad = checks.filter((c) => !c.ok)
  const crit = bad.filter((c) => c.critical)
  return checks.length - bad.length + '/' + checks.length + ' ok' + (crit.length ? ', critical: ' + crit.map((c) => c.name).join(', ') : '')
}

export function checkLine(c: Check): string {
  return (c.ok ? 'ok   ' : c.critical ? 'RED  ' : 'warn ') + c.name + (c.detail ? '  ' + c.detail : '')
}

export function fleetText(checks: Check[], surfaces: Surface[], error: string | null): string {
  if (error) return 'Fleet doctor failed: ' + error
  const lines = ['Fleet: ' + summary(checks), ...checks.map(checkLine)]
  if (surfaces.length) lines.push('', 'CLI surfaces:', ...surfaces.map((s) => '  ' + s.name.padEnd(9) + (s.fleet ? 'FLEET     ' : 'NOT-FLEET ') + s.base))
  return lines.join('\n')
}
