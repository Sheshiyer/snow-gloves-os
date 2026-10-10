// sg-catalog: the catalog browser and the intake for third-party mods.
//   /sg-catalog          a pane over catalog/modules.json with category and disposition filters. Enable runs
//                        scripts/onboard.py --tenant T --enable ID after a confirmation. hold and refuse cards
//                        show their refusal and no button, so the connector gate's rule is visible here too.
//   /sg-mod-review PATH  runs `claude plugin validate --json` on a third-party mod and has sg_mods.py draft-card
//                        write a hold card with what the mod hooks and calls. Nothing is installed or enabled.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { Card } from '../types'
import { ALL, SHOWN, canEnable, cardIdFor, cardLine, distinct, draftResult, filterCards, listText, platformRootFrom, refusal, tableFrom } from './lib'

const PANE = 'sg-catalog'
const RUN_TIMEOUT_MS = 30_000

const cards = atom({ plugin: 'sg-catalog', key: 'cards' } as const, [])
const enabled = atom({ plugin: 'sg-catalog', key: 'enabled' } as const, [])
const tenantName = atom({ plugin: 'sg-catalog', key: 'tenant' } as const, null)
const category = atom({ plugin: 'sg-catalog', key: 'category' } as const, 'all')
const disposition = atom({ plugin: 'sg-catalog', key: 'disposition' } as const, 'all')
const error = atom({ plugin: 'sg-catalog', key: 'error' } as const, null)
const note = atom({ plugin: 'sg-catalog', key: 'note' } as const, null)

let pluginOptions: PluginOptions = {}
let isWorking = false

async function settingsOf($: EngineInterface) {
  const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
  const dataRoot = String(pluginOptions.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
  const tenant = String(pluginOptions.tenant || '') || (await $.env.get('SNOWGLOVES_TENANT')) || ''
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  return { root, dataRoot, tenant, python }
}

// Never rejects
async function load($: EngineInterface) {
  try {
    const cfg = await settingsOf($)
    const argv = [cfg.python, cfg.root + '/scripts/sg_mods.py', 'catalog']
    if (cfg.tenant) argv.push('--tenant', cfg.tenant)
    if (cfg.dataRoot) argv.push('--data-root', cfg.dataRoot)
    const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS })
    const table = tableFrom(run.stdout)
    if (table === null) {
      await update($, error, () => run.stdout.trim() || run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode)
      return
    }
    await update($, cards, () => table.cards)
    await update($, enabled, () => table.enabled)
    await update($, tenantName, () => table.tenant)
    await update($, error, () => null)
  } catch (err) {
    await update($, error, () => String(err instanceof Error ? err.message : err)).catch(() => undefined)
  }
}

async function enable($: EngineInterface, card: Card) {
  if (isWorking) return
  isWorking = true
  try {
    const cfg = await settingsOf($)
    if (!cfg.tenant) {
      await update($, note, () => 'No tenant: set SNOWGLOVES_TENANT or the tenant option')
      return
    }
    let answer: string | undefined
    try {
      answer = await $.ui.ask('Enable ' + card.id + ' (risk ' + card.risk + ') for ' + cfg.tenant + '?', ['Enable', 'Cancel'])
    } catch {
      answer = undefined
    }
    if (answer !== 'Enable') {
      await update($, note, () => 'Left ' + card.id + ' disabled')
      return
    }
    const argv = [cfg.python, cfg.root + '/scripts/onboard.py', '--tenant', cfg.tenant, '--enable', card.id]
    if (cfg.dataRoot) argv.push('--data', cfg.dataRoot)
    const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS })
    const text = run.exitCode === 0 ? 'Enabled ' + card.id + ' for ' + cfg.tenant : 'Could not enable ' + card.id + ': ' + (run.stderr.trim().split('\n').pop() || run.stdout.trim().split('\n').pop() || 'exit ' + run.exitCode)
    await update($, note, () => text)
    if (run.exitCode === 0) $.ui.toast(text)
    await load($)
  } catch (err) {
    await update($, note, () => 'Could not enable ' + card.id + ': ' + String(err instanceof Error ? err.message : err))
  } finally {
    isWorking = false
  }
}

async function review($: EngineInterface, path: string): Promise<string> {
  const target = path.trim()
  if (!target) return 'Usage: /sg-mod-review <path to a mod folder>'
  const id = cardIdFor(target)
  if (!id) return 'Cannot name a card from that path.'
  const cfg = await settingsOf($)
  const validate = await $.process.run(['claude', 'plugin', 'validate', '--json', target], { cwd: cfg.root, timeoutMs: RUN_TIMEOUT_MS })
  if (!validate.stdout.trim().startsWith('{')) return 'Validate printed no report: ' + (validate.stderr.trim().split('\n').pop() || 'exit ' + validate.exitCode)
  const run = await $.process.run([cfg.python, cfg.root + '/scripts/sg_mods.py', 'draft-card', '--id', id, '--source', target], {
    cwd: cfg.root,
    stdin: validate.stdout,
    timeoutMs: RUN_TIMEOUT_MS,
  })
  const drafted = draftResult(run.stdout)
  if ('error' in drafted) return 'No card drafted: ' + drafted.error
  const flags = drafted.flags.length ? 'Flags: ' + drafted.flags.join(', ') + '.' : 'No rule flags.'
  return 'Drafted a hold card: ' + drafted.card + '. ' + flags + ' Nothing was installed or enabled; review the card, then run scripts/build_catalog.py.'
}

export const register: Register = (on, options) => {
  pluginOptions = options

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'sg-catalog', description: 'Browse the Snow Gloves catalog and enable a card', immediate: true })
    await $.command.register({ name: 'sg-mod-review', description: 'Draft a hold card for a third-party mod folder', argumentHint: '<path>', immediate: false })
    return next(e)
  })

  on('command.run', { command: 'sg-catalog' }, async ($) => {
    await load($)
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'Catalog', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    const reason = await read($, error)
    if (reason !== null) return { text: 'Catalog unavailable: ' + reason }
    return { text: listText(await read($, cards), await read($, enabled), await read($, tenantName)) }
  })

  on('command.run', { command: 'sg-mod-review' }, async ($, e) => {
    try {
      return { text: await review($, e.args) }
    } catch (err) {
      return { text: 'Review failed: ' + String(err instanceof Error ? err.message : err) }
    }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Select, Text } = $.ui.resolve(e)
    const all: Card[] = await read($, cards)
    const on_ = await read($, enabled)
    const tenant = await read($, tenantName)
    const cat = await read($, category)
    const disp = await read($, disposition)
    const reason = await read($, error)
    const last = await read($, note)
    const shown = filterCards(all, cat, disp)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Catalog' + (tenant ? ' for ' + tenant : '') + ': ' + shown.length + ' of ' + all.length + ' cards, ' + on_.length + ' enabled'}</Text>
          <Button key="reload" label="reload" hotkey="r" plain onPress={() => load($)} />
        </Box>
        <Box flexDirection="row" columnGap={2}>
          <Select key="filter-category" label="category" value={cat} options={distinct(all, 'category').map((v) => ({ value: v, label: v }))} onSelect={(v) => update($, category, () => v)} />
          <Select key="filter-disposition" label="disposition" value={disp} options={distinct(all, 'disposition').map((v) => ({ value: v, label: v }))} onSelect={(v) => update($, disposition, () => v)} />
        </Box>
        {reason !== null && <Text color="red">{'Catalog unavailable: ' + reason}</Text>}
        {shown.slice(0, SHOWN).map((card) => (
          <Box flexDirection="column" key={'card-' + card.id}>
            <Text wrap="truncate-end">{cardLine(card, on_)}</Text>
            <Box flexDirection="row" columnGap={2}>
              <Text dimColor wrap="truncate-end">{'  ' + card.summary}</Text>
              {canEnable(card, on_) && <Button key={'enable-' + card.id} label="enable" onPress={() => enable($, card)} />}
              {refusal(card) !== null && !on_.includes(card.id) && <Text color="yellow">{refusal(card)}</Text>}
            </Box>
          </Box>
        ))}
        {shown.length > SHOWN && <Text dimColor>{shown.length - SHOWN + ' more: narrow the filters'}</Text>}
        {last !== null && <Text dimColor>{last}</Text>}
      </Box>
    )
  })
}
