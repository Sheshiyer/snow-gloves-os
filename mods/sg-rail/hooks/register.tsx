// sg-rail: the Snow Gloves status band above the prompt, and /sg.
// It reads scripts/sg_mods.py snapshot every 30 seconds, probes Hermes and OmniRoute,
// and shows the Temperance rail that PromptProcessing writes to a file while this mod sets
// TEMPERANCE_RAIL_SINK=file. It changes nothing on disk.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import { asRailUi, asSnapshot, bandLines, parseJson, platformRootFrom, summaryText } from './lib'

const snapshot = atom({ plugin: 'sg-rail', key: 'snapshot' } as const, null)
const health = atom({ plugin: 'sg-rail', key: 'health' } as const, { hermes: null, omniroute: null })
const rail = atom({ plugin: 'sg-rail', key: 'rail' } as const, null)
const error = atom({ plugin: 'sg-rail', key: 'error' } as const, null)
const isHidden = atom({ plugin: 'sg-rail', key: 'isHidden' } as const, false)

const REFRESH_MS = 30_000
const PROBE_MS = 2_500
const SNAPSHOT_TIMEOUT_MS = 15_000

// One refresh at a time: a caller that arrives mid-refresh waits for the one in flight
let inflight: Promise<void> | null = null

async function settingsOf($: EngineInterface, options: PluginOptions) {
  const root = String(options.platformRoot || '') || platformRootFrom($.plugin.root)
  const tenant = String(options.tenant || '') || (await $.env.get('SNOWGLOVES_TENANT')) || ''
  const dataRoot = String(options.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  return { root, tenant, dataRoot, python }
}

async function probe($: EngineInterface, url: string): Promise<boolean> {
  const answered = $.http.fetch(url).then(
    (response) => response.ok,
    () => false,
  )
  const timedOut = $.clock.sleep(PROBE_MS).then(() => false)
  return Promise.race([answered, timedOut])
}

function refresh($: EngineInterface, options: PluginOptions): Promise<void> {
  if (!inflight) inflight = refreshOnce($, options).finally(() => (inflight = null))
  return inflight
}

// Never rejects: it runs from timers and unawaited calls, where nothing would handle a rejection
async function refreshOnce($: EngineInterface, options: PluginOptions) {
  try {
    const cfg = await settingsOf($, options)
    const argv = [cfg.python, cfg.root + '/scripts/sg_mods.py', 'snapshot', '--cwd', await $.session.cwd()]
    if (cfg.tenant) argv.push('--tenant', cfg.tenant)
    if (cfg.dataRoot) argv.push('--data-root', cfg.dataRoot)
    const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: SNAPSHOT_TIMEOUT_MS })
    const snap = asSnapshot(parseJson(run.stdout))
    await update($, error, () => (snap ? null : run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode))
    if (snap) {
      await update($, snapshot, () => snap)
      const [hermes, omniroute] = await Promise.all([
        probe($, snap.endpoints.hermes + '/healthz'),
        probe($, snap.endpoints.omniroute + '/healthz'),
      ])
      await update($, health, () => ({ hermes, omniroute }))
    }
  } catch (err) {
    const reason = String(err instanceof Error ? err.message : err)
    await update($, error, () => reason).catch(() => undefined)
  }
}

// Never rejects, for the same reason as refresh
async function readRail($: EngineInterface) {
  try {
    const home = await $.env.get('HOME')
    if (!home) return
    const path = home + '/.claude/MEMORY/STATE/rail/' + (await $.session.id()) + '.ui.json'
    if (!(await $.fs.exists(path))) return
    const ui = asRailUi(parseJson(await $.fs.read(path)))
    if (ui) await update($, rail, () => ui)
  } catch {
    // An unreadable sink leaves the last rail on screen
  }
}

async function openApprovals($: EngineInterface) {
  const commands = await $.command.list()
  if (!commands.some((command) => command.name === 'approvals')) {
    $.ui.toast('Install sg-approvals for /approvals')
    return
  }
  await $.command.run({ command: 'approvals' })
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    // PromptProcessing writes the rail to a file instead of Claude's context while this is set
    await $.env.set('TEMPERANCE_RAIL_SINK', 'file')
    $.clock.every(REFRESH_MS, async () => {
      await refresh($, options)
      await readRail($)
    })
    void refresh($, options)
    void readRail($)
    await $.command.register({
      name: 'sg',
      description: 'Snow Gloves status: tenant, data root, services, approvals, rail',
      argumentHint: '[show|hide]',
      immediate: true,
    })
    return next(e)
  })

  // /clear, /resume and /branch reset $.state, so read everything again
  on('classic.SessionStart', { source: ['clear', 'resume', 'fork'] }, async ($, e, next) => {
    void refresh($, options)
    void readRail($)
    return next(e)
  })

  // PromptProcessing writes the sink while the prompt is submitted
  on('turn.start', async ($, e, next) => {
    void readRail($)
    return next(e)
  })

  on('command.run', { command: 'sg' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg === 'hide' || arg === 'show') {
      await update($, isHidden, () => arg === 'hide')
      return { text: 'Band ' + (arg === 'hide' ? 'hidden' : 'shown') }
    }
    await refresh($, options)
    await readRail($)
    return {
      text: summaryText(await read($, snapshot), await read($, health), await read($, rail), await read($, error)),
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const snap = await read($, snapshot)
    const reason = await read($, error)
    if (e.props.hasSurvey || (await read($, isHidden)) || (snap === null && reason === null)) return next(e)
    const lines = bandLines(snap, await read($, health), await read($, rail), reason, e.props.bodyColumns)
    const { Box, Button, Text } = $.ui.resolve(e)
    const theirs = await next(e)
    return (
      <Box flexDirection="column">
        {lines.map((line, i) => (
          <Text dimColor={i > 0} wrap="truncate-end">
            {line}
          </Text>
        ))}
        <Box flexDirection="row" columnGap={2}>
          <Button key="sg-approvals" label="approvals" hotkey="a" plain onPress={() => openApprovals($)} />
          <Button key="sg-hide" label="hide" hotkey="h" plain onPress={() => update($, isHidden, () => true)} />
        </Box>
        {theirs}
      </Box>
    )
  })
}
