// Pure helpers for sg-handoff. No $ here.
import type { Held } from '../types'

export const TAG = '[sg]'
export const FORK_PROMPT =
  'Write a handoff for another Claude Code session that will continue this work. Use Markdown with four headings: ' +
  'Goal, State (what is done and verified, what is not), Open questions, Next step. Name files and commands exactly. ' +
  'Stay under 400 words and do not call tools.'

export function platformRootFrom(pluginRoot: string): string {
  return pluginRoot.split('/').slice(0, -2).join('/')
}

export type Args = { sessionId: string | null }
export function parseArgs(args: string): Args {
  const id = args.trim().split(/\s+/)[0]
  return { sessionId: id ? id : null }
}

export function pointer(path: string, from: string): string {
  return TAG + ' Handoff from session ' + from + ' is written to ' + path + '. Read it, then continue from "Next step".'
}

// Whether the inbox keeps this message: mode on, a peer's, and tagged for Snow Gloves.
export function isHeldKind(on: boolean, originKind: string, text: string): boolean {
  return on && (originKind === 'peer' || originKind === 'peer-send-message') && text.trimStart().startsWith(TAG)
}

export function addHeld(held: Held[], id: number, text: string, from: string, at: number): Held[] {
  return [...held, { id, text: text.trimStart().slice(TAG.length).trim(), from, at }].slice(-50)
}

export function heldLine(h: Held, now: number): string {
  const mins = Math.max(0, Math.floor((now - h.at) / 60))
  return mins + 'm  ' + h.from + '  ' + h.text.split('\n')[0]
}

export function inboxText(held: Held[], now: number, isOn: boolean): string {
  const head = 'Inbox is ' + (isOn ? 'on' : 'off') + ': ' + held.length + ' held'
  return [head, ...held.map((h) => heldLine(h, now))].join('\n')
}

export function writeResult(stdout: string): { path: string } | { error: string } {
  try {
    const out = JSON.parse(stdout)
    if (typeof out.path === 'string') return { path: out.path }
    return { error: String(out.error || 'write-handoff returned no path') }
  } catch {
    return { error: 'write-handoff printed no JSON' }
  }
}
