// sg-handoff: the transfer dock and the attention inbox.
//   /handoff [sessionId]  asks the session's own model for a handoff over its cached transcript, shows it
//                         for confirmation, writes .project/HANDOFF.md through sg_mods.py write-handoff (a
//                         CLI, rule I6), and tells the other session where it is.
//   /inbox [on|off]       with inbox mode on, peer messages tagged [sg] are held in a pane instead of
//                         interrupting the running turn. Hand to Claude submits one as a turn.
// Hand to Claude is the one use of $.prompt.submit, and it runs only from a button a person pressed.
// That is the documented exception to rule I3 (docs/mods.md).
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Held } from '../types'
import { FORK_PROMPT, addHeld, inboxText, isHeldKind, parseArgs, platformRootFrom, pointer, writeResult } from './lib'

const PANE = 'sg-handoff'
const RUN_TIMEOUT_MS = 15_000

const held = atom({ plugin: 'sg-handoff', key: 'held' } as const, [])
const isInboxOn = atom({ plugin: 'sg-handoff', key: 'isInboxOn' } as const, false)
const note = atom({ plugin: 'sg-handoff', key: 'note' } as const, null)
const nextId = atom({ plugin: 'sg-handoff', key: 'nextId' } as const, 1)

let pluginOptions: PluginOptions = {}

async function handoff($: EngineInterface, sessionId: string | null): Promise<string> {
  const reply = await $.model.fork({ prompt: FORK_PROMPT })
  if (!reply.isAnswered) return 'No handoff written: ' + reply.reason
  const cwd = await $.session.cwd()
  const me = await $.session.id()
  const where = sessionId ? ' and tell session ' + sessionId : ''
  let answer: string | undefined
  try {
    answer = await $.ui.ask('Write ' + cwd + '/.project/HANDOFF.md' + where + '?\n\n' + reply.text.slice(0, 1500), ['Write', 'Cancel'])
  } catch {
    answer = undefined
  }
  if (answer !== 'Write') return 'Handoff not written (cancelled).'
  const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  const run = await $.process.run([python, root + '/scripts/sg_mods.py', 'write-handoff', '--cwd', cwd, '--session', me], {
    cwd: root,
    stdin: reply.text,
    timeoutMs: RUN_TIMEOUT_MS,
  })
  const wrote = writeResult(run.stdout)
  if ('error' in wrote) return 'Handoff not written: ' + wrote.error
  if (!sessionId) return 'Handoff written to ' + wrote.path
  const sent = await $.session.send({ to: { sessionId }, text: pointer(wrote.path, me) })
  if (!sent.isDelivered) {
    $.ui.toast('Handoff written, but session ' + sessionId + ' was not told: ' + sent.reason)
    return 'Handoff written to ' + wrote.path + '. Not delivered to ' + sessionId + ': ' + sent.reason
  }
  return 'Handoff written to ' + wrote.path + ' and session ' + sessionId + ' told.'
}

async function handToClaude($: EngineInterface, item: Held) {
  await update($, held, (old: Held[]) => old.filter((x) => x.id !== item.id))
  await update($, note, () => 'Handed message ' + item.id + ' to Claude')
  await $.prompt.submit({ text: item.text })
}

export const register: Register = (on, options) => {
  pluginOptions = options

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'handoff', description: 'Write .project/HANDOFF.md and tell another session', argumentHint: '[sessionId]', immediate: false })
    await $.command.register({ name: 'inbox', description: 'Hold [sg] messages from other sessions', argumentHint: '[on|off]', immediate: true })
    return next(e)
  })

  on('command.run', { command: 'handoff' }, async ($, e) => ({ text: await handoff($, parseArgs(e.args).sessionId) }))

  on('command.run', { command: 'inbox' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg === 'on' || arg === 'off') await update($, isInboxOn, () => arg === 'on')
    const now = Math.floor((await $.clock.now()) / 1000)
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'Inbox', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    return { text: inboxText(await read($, held), now, await read($, isInboxOn)) }
  })

  on('session.receive', async ($, e, next) => {
    const isOn = await read($, isInboxOn)
    if (!isHeldKind(isOn, e.origin.kind, e.text)) return next(e)
    const id = await read($, nextId)
    const at = Math.floor((await $.clock.now()) / 1000)
    await update($, nextId, () => id + 1)
    await update($, held, (old: Held[]) => addHeld(old, id, e.text, e.origin.kind, at))
    $.ui.toast('Inbox: 1 message held (/inbox)')
    return { consumed: 'Held in /inbox' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list: Held[] = await read($, held)
    const isOn = await read($, isInboxOn)
    const last = await read($, note)
    const now = Math.floor((await $.clock.now()) / 1000)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Inbox is ' + (isOn ? 'on' : 'off') + ': ' + list.length + ' held'}</Text>
          <Button key="toggle" label={isOn ? 'turn off' : 'turn on'} hotkey="t" plain onPress={() => update($, isInboxOn, (v: boolean) => !v)} />
        </Box>
        {list.length === 0 && <Text dimColor>Nothing held.</Text>}
        {list.map((item) => (
          <Box flexDirection="column" key={'held-' + item.id}>
            <Text wrap="truncate-end">{item.text.split('\n')[0]}</Text>
            <Box flexDirection="row" columnGap={2}>
              <Text dimColor>{Math.max(0, Math.floor((now - item.at) / 60)) + 'm · ' + item.from}</Text>
              <Button key={'hand-' + item.id} label="hand to Claude" onPress={() => handToClaude($, item)} />
              <Button key={'drop-' + item.id} label="dismiss" onPress={() => update($, held, (old: Held[]) => old.filter((x) => x.id !== item.id))} />
            </Box>
          </Box>
        ))}
        {last !== null && <Text dimColor>{last}</Text>}
      </Box>
    )
  })
}
