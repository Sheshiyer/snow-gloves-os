// Pure helpers for sg-catalog. No $ here.
import type { Card } from '../types'

export const ALL = 'all'
export const SHOWN = 40

export function platformRootFrom(pluginRoot: string): string {
  return pluginRoot.split('/').slice(0, -2).join('/')
}

export type Table = { cards: Card[]; enabled: string[]; tenant: string | null }

export function tableFrom(stdout: string): Table | null {
  try {
    const data = JSON.parse(stdout)
    if (!data || !Array.isArray(data.cards)) return null
    return { cards: data.cards, enabled: Array.isArray(data.enabled) ? data.enabled : [], tenant: typeof data.tenant === 'string' ? data.tenant : null }
  } catch {
    return null
  }
}

export function filterCards(cards: Card[], category: string, disposition: string): Card[] {
  return cards.filter((c) => (category === ALL || c.category === category) && (disposition === ALL || c.disposition === disposition))
}

export function distinct(cards: Card[], field: 'category' | 'disposition'): string[] {
  return [ALL, ...[...new Set(cards.map((c) => c[field]))].sort()]
}

// hold and refuse cards are never enabled; a card the catalog marks not enableable (pointers, playbooks) has no button either.
export function canEnable(card: Card, enabled: string[]): boolean {
  return card.enableable && (card.disposition === 'add') && !enabled.includes(card.id)
}

export function refusal(card: Card): string | null {
  if (card.disposition === 'refuse') return 'refused: the platform never enables this'
  if (card.disposition === 'hold') return 'on hold: review the card first; it is not enabled'
  if (card.disposition === 'pointer') return 'pointer only: nothing to enable'
  if (!card.enableable) return 'not enableable'
  return null
}

export function cardLine(card: Card, enabled: string[]): string {
  const mark = enabled.includes(card.id) ? '● ' : '  '
  return mark + card.id + '  ' + card.disposition + '  ' + card.category + '  risk ' + card.risk + (card.approval === 'yes' ? '  approval' : '')
}

export function listText(cards: Card[], enabled: string[], tenant: string | null): string {
  const head = 'Catalog' + (tenant ? ' for ' + tenant : '') + ': ' + cards.length + ' cards, ' + enabled.length + ' enabled'
  return [head, ...cards.slice(0, SHOWN).map((c) => cardLine(c, enabled))].join('\n')
}

// A card id for a third-party mod folder: its basename, lower-cased, safe characters only.
export function cardIdFor(path: string): string {
  const base = path.replace(/\/+$/, '').split('/').pop() || ''
  return base.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '')
}

export function draftResult(stdout: string): { card: string; flags: string[] } | { error: string } {
  try {
    const out = JSON.parse(stdout)
    if (typeof out.card === 'string') return { card: out.card, flags: Array.isArray(out.flags) ? out.flags : [] }
    return { error: String(out.error || 'draft-card returned no card') }
  } catch {
    return { error: 'draft-card printed no JSON' }
  }
}
