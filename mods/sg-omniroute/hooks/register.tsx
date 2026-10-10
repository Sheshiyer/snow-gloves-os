// sg-omniroute: a ledger of what each model request cost. A turn.step hook records the tokens, cache use
// and model of every request (the main conversation and each subagent apart); a band above the prompt
// shows context, rate limits, cache share and cost; /omniroute opens the ledger and /combo lists the
// gateway's combos. Read-only toward OmniRoute: the combos come from its database opened read-only by
// scripts/sg_mods.py, and the mod never touches its key or changes the session's model.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Row } from '../types'
import { addRow, comboLine, combosFrom, ledgerText, meterText, platformRootFrom, rowLine, rowOf, totalLine, totalsByModel } from './lib'

const PANE = 'sg-omniroute'
const COMBO_PANE = 'sg-omniroute-combos'
const RUN_TIMEOUT_MS = 15_000

const rows = atom({ plugin: 'sg-omniroute', key: 'rows' } as const, [])
const combos = atom({ plugin: 'sg-omniroute', key: 'combos' } as const, [])
const comboError = atom({ plugin: 'sg-omniroute', key: 'comboError' } as const, null)
const meter = atom({ plugin: 'sg-omniroute', key: 'meter' } as const, null)

let pluginOptions: PluginOptions = {}

async function loadCombos($: EngineInterface) {
  try {
    const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
    const venv = root + '/.venv/bin/python'
    const python = (await $.fs.exists(venv)) ? venv : 'python3'
    const argv = [python, root + '/scripts/sg_mods.py', 'combos']
    const db = String(pluginOptions.combosDb || '')
    if (db) argv.push('--db', db)
    const run = await $.process.run(argv, { cwd: root, timeoutMs: RUN_TIMEOUT_MS })
    const list = combosFrom(run.stdout)
    if (list === null) {
      await update($, comboError, () => run.stdout.trim() || run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode)
      return
    }
    await update($, combos, () => list)
    await update($, comboError, () => null)
  } catch (err) {
    await update($, comboError, () => String(err instanceof Error ? err.message : err)).catch(() => undefined)
  }
}

async function refreshMeter($: EngineInterface) {
  try {
    const held: Row[] = await read($, rows)
    const usage = await $.session.usage()
    await update($, meter, () => meterText(usage, held))
  } catch {
    // the meter keeps its last text
  }
}

export const register: Register = (on, options) => {
  pluginOptions = options

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'omniroute', description: 'Per-request token, cache and model ledger', immediate: true })
    await $.command.register({ name: 'combo', description: "List the OmniRoute gateway's combos", immediate: true })
    return next(e)
  })

  // The ledger only watches: the request and its result go through as they came
  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    try {
      const row = rowOf(result.turnId, result.index, e.agentId, e.model, result.usage)
      if (row) {
        await update($, rows, (old: Row[]) => addRow(old, row))
        await refreshMeter($)
      }
    } catch {
      // a ledger failure never touches the turn
    }
    return result
  })

  on('command.run', { command: 'omniroute' }, async ($) => {
    const drawn = (await $.session.surfaces()).length > 0
    await refreshMeter($)
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'OmniRoute', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    return { text: ledgerText(await read($, rows)) }
  })

  on('command.run', { command: 'combo' }, async ($) => {
    await loadCombos($)
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: COMBO_PANE, title: 'Combos', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    const reason = await read($, comboError)
    if (reason !== null) return { text: 'Combos unavailable: ' + reason }
    const list = await read($, combos)
    return { text: list.length ? list.map(comboLine).join('\n') : 'OmniRoute has no combos.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const text = await read($, meter)
    if (e.props.hasSurvey || text === null) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const theirs = await next(e)
    return (
      <Box flexDirection="column">
        <Text dimColor wrap="truncate-end">{text}</Text>
        {theirs}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const held: Row[] = await read($, rows)
    const totals = totalsByModel(held)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'OmniRoute ledger: ' + held.length + ' requests'}</Text>
          <Button key="refresh" label="refresh" hotkey="r" plain onPress={() => refreshMeter($)} />
        </Box>
        {held.length === 0 && <Text dimColor>No requests recorded yet.</Text>}
        {totals.map((t) => (
          <Text key={'total-' + t.model} wrap="truncate-end">{totalLine(t)}</Text>
        ))}
        {held.length > 0 && <Text bold>Latest</Text>}
        {held.slice(-15).reverse().map((r) => (
          <Text key={'row-' + r.turnId + '-' + r.index + '-' + r.agent} dimColor wrap="truncate-end">{rowLine(r)}</Text>
        ))}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: COMBO_PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list = await read($, combos)
    const reason = await read($, comboError)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Combos: ' + list.length}</Text>
          <Button key="reload" label="reload" hotkey="r" plain onPress={() => loadCombos($)} />
        </Box>
        {reason !== null && <Text color="red">{'Combos unavailable: ' + reason}</Text>}
        {list.map((c) => (
          <Text key={'combo-' + c.name} wrap="truncate-end">{comboLine(c)}</Text>
        ))}
      </Box>
    )
  })
}
