// sg-fleet: the fleet cockpit. /fleet opens a pane of this wing's doctor checks and the CLI surfaces'
// gateway state; a timer re-reads both every two minutes and toasts when a critical check turns red.
// Both come from the platform's own read-only scripts (scripts/fleet/doctor.py, gateway_client.py status).
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import { checksFrom, fleetText, newlyRed, platformRootFrom, summary, surfacesFrom } from './lib'

const PANE = 'sg-fleet'
const REFRESH_MS = 120_000
const RUN_TIMEOUT_MS = 45_000

const checks = atom({ plugin: 'sg-fleet', key: 'checks' } as const, [])
const surfaces = atom({ plugin: 'sg-fleet', key: 'surfaces' } as const, [])
const error = atom({ plugin: 'sg-fleet', key: 'error' } as const, null)
const checkedAt = atom({ plugin: 'sg-fleet', key: 'checkedAt' } as const, null)

let before: ReturnType<typeof checksFrom> = null
let pluginOptions: PluginOptions = {}

async function settingsOf($: EngineInterface) {
  const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
  const dataRoot = String(pluginOptions.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  return { root, dataRoot, python }
}

// Never rejects: it runs from a timer
async function refresh($: EngineInterface) {
  try {
    const cfg = await settingsOf($)
    const doctor = [cfg.python, cfg.root + '/scripts/fleet/doctor.py', '--json']
    if (cfg.dataRoot) doctor.push('--root', cfg.dataRoot)
    const [run, gw] = await Promise.all([
      $.process.run(doctor, { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS }),
      $.process.run([cfg.python, cfg.root + '/scripts/fleet/gateway_client.py', 'status'], { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS }),
    ])
    const list = checksFrom(run.stdout)
    if (list === null) {
      await update($, error, () => run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode)
      return
    }
    const red = newlyRed(before, list)
    before = list
    await update($, checks, () => list)
    await update($, surfaces, () => surfacesFrom(gw.stdout))
    await update($, error, () => null)
    const stamp = Math.floor((await $.clock.now()) / 1000)
    await update($, checkedAt, () => stamp)
    if (red.length > 0) $.ui.toast('Fleet critical check red: ' + red.join(', ') + ' (/fleet)')
  } catch (err) {
    const reason = String(err instanceof Error ? err.message : err)
    await update($, error, () => reason).catch(() => undefined)
  }
}

export const register: Register = (on, options) => {
  pluginOptions = options

  on('session.start', async ($, e, next) => {
    $.clock.every(REFRESH_MS, () => refresh($))
    void refresh($)
    await $.command.register({ name: 'fleet', description: 'Snow Gloves fleet doctor and gateway state', immediate: true })
    return next(e)
  })

  on('command.run', { command: 'fleet' }, async ($) => {
    await refresh($)
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'Fleet', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    return { text: fleetText(await read($, checks), await read($, surfaces), await read($, error)) }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list = await read($, checks)
    const gw = await read($, surfaces)
    const reason = await read($, error)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Fleet: ' + summary(list)}</Text>
          <Button key="refresh" label="refresh" hotkey="r" plain onPress={() => refresh($)} />
        </Box>
        {reason !== null && <Text color="red">{'Doctor failed: ' + reason}</Text>}
        {list.map((c) => (
          <Text key={'check-' + c.name} color={c.ok ? 'green' : c.critical ? 'red' : 'yellow'} wrap="truncate-end">
            {(c.ok ? '● ' : '○ ') + c.name + '  ' + c.detail}
          </Text>
        ))}
        {gw.length > 0 && <Text bold>CLI surfaces</Text>}
        {gw.map((s) => (
          <Text key={'surface-' + s.name} color={s.fleet ? 'green' : 'yellow'} wrap="truncate-end">
            {(s.fleet ? '● ' : '○ ') + s.name + '  ' + (s.fleet ? 'FLEET  ' : 'NOT-FLEET  ') + s.base}
          </Text>
        ))}
      </Box>
    )
  })
}
