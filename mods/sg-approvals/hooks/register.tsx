// sg-approvals: the review desk. /approvals opens a pane of pending tickets across tenants.
// Approve and Reject are buttons only a person can press: the mod adds no tool for Claude and
// submits no prompt, so a decision never comes from the model. Decisions go through
// scripts/approvals.py, which records the actor and moves the ticket to history.jsonl.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Ticket } from '../types'
import { isHighRisk, newIds, platformRootFrom, ticketLine, ticketsFrom } from './lib'

const PANE = 'sg-approvals'
const REFRESH_MS = 30_000
const RUN_TIMEOUT_MS = 15_000

const tickets = atom({ plugin: 'sg-approvals', key: 'tickets' } as const, [])
const error = atom({ plugin: 'sg-approvals', key: 'error' } as const, null)
const note = atom({ plugin: 'sg-approvals', key: 'note' } as const, null)

// Ticket ids from the last look, so the timer can say when new ones arrive
let seen: Set<string> | null = null
// One decision at a time, so a double press can't decide twice
let isDeciding = false
let pluginOptions: PluginOptions = {}

async function settingsOf($: EngineInterface) {
  const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
  const dataRoot = String(pluginOptions.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
  const actor =
    String(pluginOptions.actor || '') ||
    (await $.env.get('SNOWGLOVES_ACTOR')) ||
    (await $.env.get('USER')) ||
    'claude-code'
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  return { root, dataRoot, actor, python }
}

function message(err: unknown): string {
  return String(err instanceof Error ? err.message : err)
}

// Never rejects: it runs from a timer
async function refresh($: EngineInterface) {
  try {
    const cfg = await settingsOf($)
    const argv = [cfg.python, cfg.root + '/scripts/sg_mods.py', 'snapshot', '--cwd', await $.session.cwd()]
    if (cfg.dataRoot) argv.push('--data-root', cfg.dataRoot)
    const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS })
    const list = ticketsFrom(run.stdout)
    if (list === null) {
      await update($, error, () => run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode)
      return
    }
    const fresh = newIds(seen, list)
    seen = new Set(list.map((t) => t.id))
    await update($, tickets, () => list)
    await update($, error, () => null)
    if (fresh.length > 0) $.ui.toast(fresh.length + ' new approval' + (fresh.length > 1 ? 's' : '') + ' waiting: /approvals')
  } catch (err) {
    const reason = message(err)
    await update($, error, () => reason).catch(() => undefined)
  }
}

async function confirmed($: EngineInterface, ticket: Ticket): Promise<boolean> {
  try {
    const what = ticket.connector + '.' + ticket.capability
    const answer = await $.ui.ask('Approve high-risk ' + what + ' for ' + ticket.tenant + '? (' + ticket.id + ')', [
      'Approve',
      'Keep pending',
    ])
    return answer === 'Approve'
  } catch {
    // Dismissed, or nobody is there to answer: leave the ticket pending
    return false
  }
}

async function decide($: EngineInterface, ticket: Ticket, verdict: 'approve' | 'reject') {
  if (isDeciding) return
  isDeciding = true
  try {
    if (verdict === 'approve' && isHighRisk(ticket) && !(await confirmed($, ticket))) {
      await update($, note, () => 'Left ' + ticket.id + ' pending')
      return
    }
    const cfg = await settingsOf($)
    const argv = [
      cfg.python, cfg.root + '/scripts/approvals.py', verdict,
      '--tenant', ticket.tenant, '--id', ticket.id, '--actor', cfg.actor,
    ]
    if (verdict === 'reject') argv.push('--reason', 'rejected in /approvals')
    if (cfg.dataRoot) argv.push('--data-root', cfg.dataRoot)
    const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS })
    let out: { ok?: boolean; error?: string } = {}
    try {
      out = JSON.parse(run.stdout)
    } catch {
      out = { error: run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode }
    }
    const done = verdict === 'approve' ? 'Approved ' : 'Rejected '
    const text = out.ok ? done + ticket.id + ' as ' + cfg.actor : 'Could not ' + verdict + ' ' + ticket.id + ': ' + out.error
    await update($, note, () => text)
    if (out.ok) $.ui.toast(text)
    await refresh($)
  } catch (err) {
    const reason = message(err)
    await update($, note, () => 'Could not ' + verdict + ' ' + ticket.id + ': ' + reason)
  } finally {
    isDeciding = false
  }
}

export const register: Register = (on, options) => {
  pluginOptions = options

  on('session.start', async ($, e, next) => {
    $.clock.every(REFRESH_MS, () => refresh($))
    void refresh($)
    await $.command.register({
      name: 'approvals',
      description: 'Review Snow Gloves approval tickets across tenants',
      immediate: true,
    })
    return next(e)
  })

  on('command.run', { command: 'approvals' }, async ($) => {
    await refresh($)
    // A plain claude -p run has no surface, and there a pane would never show
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'Approvals', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    // Nothing draws the pane here: list the tickets as text instead
    const list = await read($, tickets)
    const now = Math.floor((await $.clock.now()) / 1000)
    const lines = list.map((t) => t.id + '  ' + ticketLine(t, now))
    return { text: list.length > 0 ? 'Pending approvals:\n' + lines.join('\n') : 'No approvals waiting.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list = await read($, tickets)
    const reason = await read($, error)
    const last = await read($, note)
    const now = Math.floor((await $.clock.now()) / 1000)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Pending approvals: ' + list.length}</Text>
          <Button key="refresh" label="refresh" hotkey="r" plain onPress={() => refresh($)} />
        </Box>
        {reason !== null && <Text color="red">{'Snapshot failed: ' + reason}</Text>}
        {list.length === 0 && reason === null && <Text dimColor>Nothing waiting.</Text>}
        {list.map((t) => (
          <Box flexDirection="column" key={'row-' + t.id}>
            <Text wrap="truncate-end">{(isHighRisk(t) ? '! ' : '  ') + ticketLine(t, now)}</Text>
            <Box flexDirection="row" columnGap={2}>
              <Text dimColor>{'  ' + t.id}</Text>
              <Button key={'approve-' + t.id} label="approve" onPress={() => decide($, t, 'approve')} />
              <Button key={'reject-' + t.id} label="reject" onPress={() => decide($, t, 'reject')} />
            </Box>
          </Box>
        ))}
        {last !== null && <Text dimColor>{last}</Text>}
      </Box>
    )
  })
}
