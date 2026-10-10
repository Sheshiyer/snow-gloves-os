// sg-hermes: the Hermes console. /hermes opens a pane with three tabs: the live event stream, a route
// lens (type a task title, see which agent and hook the current skill-hooks.yaml picks), and a replay of
// recent events through today's hooks. With publishTurns on, a finished turn posts a claude.turn event to
// Hermes /publish, which gives sentinel_sweep.py real traffic to measure.
// $.http.fetch only goes to the Hermes endpoint (option, else the platform snapshot's, else :4100).
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { HermesEvent } from '../types'
import { eventLine, eventsFrom, hermesUrl, mergeEvents, newestTs, platformRootFrom, replayFrom, replayLine, routeLine, routesFrom, turnEvent } from './lib'

const PANE = 'sg-hermes'
const POLL_MS = 5_000
const RUN_TIMEOUT_MS = 20_000
const FETCH_MS = 4_000

const events = atom({ plugin: 'sg-hermes', key: 'events' } as const, [])
const tab = atom({ plugin: 'sg-hermes', key: 'tab' } as const, 'live')
const routes = atom({ plugin: 'sg-hermes', key: 'routes' } as const, null)
const routedTitle = atom({ plugin: 'sg-hermes', key: 'routedTitle' } as const, '')
const replay = atom({ plugin: 'sg-hermes', key: 'replay' } as const, null)
const error = atom({ plugin: 'sg-hermes', key: 'error' } as const, null)
const up = atom({ plugin: 'sg-hermes', key: 'up' } as const, null)

let pluginOptions: PluginOptions = {}
let baseUrl = ''
let publishTurns = false

async function settingsOf($: EngineInterface) {
  const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
  const dataRoot = String(pluginOptions.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  return { root, dataRoot, python }
}

async function resolveUrl($: EngineInterface) {
  const option = String(pluginOptions.hermesUrl || '')
  if (option) {
    baseUrl = hermesUrl(option, null)
    return
  }
  let out: string | null = null
  try {
    const cfg = await settingsOf($)
    const argv = [cfg.python, cfg.root + '/scripts/sg_mods.py', 'snapshot', '--cwd', await $.session.cwd()]
    if (cfg.dataRoot) argv.push('--data-root', cfg.dataRoot)
    out = (await $.process.run(argv, { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS })).stdout
  } catch {
    out = null
  }
  baseUrl = hermesUrl('', out)
}

// A fetch that gives up after FETCH_MS rather than hanging a timer tick
async function call($: EngineInterface, path: string, init?: { method: string; headers: Record<string, string>; body: string }) {
  const answered = $.http.fetch(baseUrl + path, init)
  const timedOut = $.clock.sleep(FETCH_MS).then(() => null)
  return Promise.race([answered, timedOut])
}

// Never rejects: it runs from a timer
async function poll($: EngineInterface) {
  try {
    if (!baseUrl) await resolveUrl($)
    const held: HermesEvent[] = await read($, events)
    const since = newestTs(held)
    const res = await call($, '/events' + (since ? '?since=' + encodeURIComponent(since) : ''))
    const list = res && res.ok ? eventsFrom(res.text) : null
    if (list === null) {
      await update($, up, () => false)
      await update($, error, () => (res ? 'Hermes answered ' + res.status : 'Hermes did not answer at ' + baseUrl))
      return
    }
    await update($, up, () => true)
    await update($, error, () => null)
    if (list.length > 0) await update($, events, (old: HermesEvent[]) => mergeEvents(old, list))
  } catch (err) {
    const reason = String(err instanceof Error ? err.message : err)
    await update($, up, () => false).catch(() => undefined)
    await update($, error, () => reason).catch(() => undefined)
  }
}

async function route($: EngineInterface, title: string) {
  const text = title.trim()
  if (!text) return
  await update($, routedTitle, () => text)
  try {
    if (!baseUrl) await resolveUrl($)
    const res = await call($, '/test/e2e', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: { title: text, tags: [], brief: text } }),
    })
    const list = res && res.ok ? routesFrom(res.text) : null
    if (list === null) {
      await update($, error, () => 'Route test failed' + (res ? ' (http ' + res.status + ')' : ': Hermes did not answer'))
      return
    }
    await update($, routes, () => list)
    await update($, error, () => null)
  } catch (err) {
    await update($, error, () => String(err instanceof Error ? err.message : err))
  }
}

async function openReplay($: EngineInterface) {
  await update($, tab, () => 'replay')
  await runReplay($)
}

async function runReplay($: EngineInterface) {
  try {
    const cfg = await settingsOf($)
    const run = await $.process.run([cfg.python, cfg.root + '/scripts/replay.py', '--last', '20'], {
      cwd: cfg.root + '/scripts',
      timeoutMs: RUN_TIMEOUT_MS,
    })
    const rows = replayFrom(run.stdout)
    if (rows === null) {
      await update($, error, () => run.stderr.trim().split('\n').pop() || 'replay exit ' + run.exitCode)
      return
    }
    await update($, replay, () => rows)
    await update($, error, () => null)
  } catch (err) {
    await update($, error, () => String(err instanceof Error ? err.message : err))
  }
}

export const register: Register = (on, options) => {
  pluginOptions = options
  publishTurns = options.publishTurns === true

  on('session.start', async ($, e, next) => {
    $.clock.every(POLL_MS, () => poll($))
    void poll($)
    await $.command.register({ name: 'hermes', description: 'Hermes events, route lens and replay', immediate: true })
    return next(e)
  })

  on('command.run', { command: 'hermes' }, async ($) => {
    await poll($)
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'Hermes', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    const held: HermesEvent[] = await read($, events)
    const reason = await read($, error)
    if (reason !== null) return { text: 'Hermes: ' + reason }
    return { text: held.length ? held.slice(-20).map(eventLine).join('\n') : 'No Hermes events yet.' }
  })

  // Posting never delays or changes the turn: a failed publish is dropped
  on('turn.complete', async ($, e, next) => {
    if (publishTurns && !e.agentId) {
      const body = turnEvent(await $.session.id(), e.durationMs, e.usage, String((await $.env.get('SNOWGLOVES_TENANT')) || ''))
      void call($, '/publish', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).catch(() => undefined)
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Input, Text } = $.ui.resolve(e)
    const current = await read($, tab)
    const reason = await read($, error)
    const isUp = await read($, up)
    const list: HermesEvent[] = await read($, events)
    const title = await read($, routedTitle)
    const found = await read($, routes)
    const rows = await read($, replay)
    const changed = (rows || []).filter((r) => r.changed)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Hermes ' + (isUp === null ? '…' : isUp ? '●' : '○')}</Text>
          <Button key="tab-live" label="live" hotkey="1" plain onPress={() => update($, tab, () => 'live')} />
          <Button key="tab-route" label="route" hotkey="2" plain onPress={() => update($, tab, () => 'route')} />
          <Button key="tab-replay" label="replay" hotkey="3" plain onPress={() => openReplay($)} />
        </Box>
        {reason !== null && <Text color="red">{reason}</Text>}
        {current === 'live' && <Text dimColor>{list.length + ' events'}</Text>}
        {current === 'live' &&
          list.slice(-30).reverse().map((ev) => (
            <Text key={'ev-' + ev.ts + ev.kind} wrap="truncate-end">{eventLine(ev)}</Text>
          ))}
        {current === 'route' && (
          <Input key="route-title" label="task title" placeholder="launch a referral program" value={title} submitLabel="route" onSubmit={(v) => route($, v)} />
        )}
        {current === 'route' && found !== null && found.length === 0 && <Text dimColor>No hook matches this title.</Text>}
        {current === 'route' &&
          (found || []).map((r, i) => (
            <Text key={'route-' + i} wrap="truncate-end">{routeLine(r)}</Text>
          ))}
        {current === 'replay' && rows === null && <Text dimColor>Running replay…</Text>}
        {current === 'replay' && rows !== null && <Text dimColor>{rows.length + ' replayed, ' + changed.length + ' would route differently'}</Text>}
        {current === 'replay' &&
          changed.map((r) => (
            <Text key={'replay-' + r.ts} wrap="truncate-end">{replayLine(r)}</Text>
          ))}
      </Box>
    )
  })
}
