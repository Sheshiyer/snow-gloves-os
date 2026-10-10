// sg-org: the seven Snow Gloves agents as Claude subagent types (sg-org:ceo, sg-org:cto, ...), built
// from agents/<slug>/ and the skill registry by scripts/sg_mods.py agents. agent.offer withholds a role the
// tenant has not enabled. agent.spawn picks a model per role, only when ANTHROPIC_BASE_URL points at the
// OmniRoute gateway, and never refuses. /org shows one lane per agent.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { OrgAgent } from '../types'
import { TYPE_PREFIX, isOffered, isOmniRoute, laneLines, orgText, parseRoleCombos, platformRootFrom, specOf, tableFrom } from './lib'

const PANE = 'sg-org'
const RUN_TIMEOUT_MS = 20_000

const agents = atom({ plugin: 'sg-org', key: 'agents' } as const, [])
const restricted = atom({ plugin: 'sg-org', key: 'restricted' } as const, false)
const tenantName = atom({ plugin: 'sg-org', key: 'tenant' } as const, null)
const error = atom({ plugin: 'sg-org', key: 'error' } as const, null)

let pluginOptions: PluginOptions = {}
let roleCombos: Record<string, string> = {}
// Copy of the table for the offer hook, so an offer never waits on a process
let table: { agents: OrgAgent[]; restricted: boolean } = { agents: [], restricted: false }

// Never rejects. Returns the agents that were found.
async function load($: EngineInterface): Promise<OrgAgent[]> {
  try {
    const root = String(pluginOptions.platformRoot || '') || platformRootFrom($.plugin.root)
    const dataRoot = String(pluginOptions.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
    const tenant = String(pluginOptions.tenant || '') || (await $.env.get('SNOWGLOVES_TENANT')) || ''
    const venv = root + '/.venv/bin/python'
    const python = (await $.fs.exists(venv)) ? venv : 'python3'
    const argv = [python, root + '/scripts/sg_mods.py', 'agents']
    if (tenant) argv.push('--tenant', tenant)
    if (dataRoot) argv.push('--data-root', dataRoot)
    const run = await $.process.run(argv, { cwd: root, timeoutMs: RUN_TIMEOUT_MS })
    const found = tableFrom(run.stdout)
    if (found === null) {
      await update($, error, () => run.stdout.trim() || run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode)
      return []
    }
    table = found
    await update($, agents, () => found.agents)
    await update($, restricted, () => found.restricted)
    await update($, tenantName, () => found.tenant)
    await update($, error, () => null)
    return found.agents
  } catch (err) {
    await update($, error, () => String(err instanceof Error ? err.message : err)).catch(() => undefined)
    return []
  }
}

export const register: Register = (on, options) => {
  pluginOptions = options
  roleCombos = parseRoleCombos(String(options.roleCombos || ''))

  on('session.start', async ($, e, next) => {
    const list = await load($)
    for (const a of list) {
      try {
        await $.agent.register(specOf(a))
      } catch (err) {
        $.ui.log('sg-org: skipped ' + a.slug + ': ' + String(err instanceof Error ? err.message : err))
      }
    }
    await $.command.register({ name: 'org', description: 'The seven Snow Gloves agents', immediate: true })
    return next(e)
  })

  on('agent.offer', async ($, e, next) => {
    if (e.provider.plugin !== 'sg-org') return next(e)
    return isOffered(table.agents, table.restricted, e.agent) ? next(e) : { isOffered: false }
  })

  on('agent.spawn', async ($, e, next) => {
    const combo = e.subagentType.startsWith(TYPE_PREFIX) ? roleCombos[e.subagentType.slice(TYPE_PREFIX.length)] : undefined
    if (!combo || !isOmniRoute(await $.env.get('ANTHROPIC_BASE_URL'))) return next(e)
    return next({ ...e, model: combo })
  })

  on('command.run', { command: 'org' }, async ($) => {
    await load($)
    const drawn = (await $.session.surfaces()).length > 0
    const placed = drawn ? await $.ui.open({ id: PANE, title: 'Org', focus: true, closeOnEscape: true }) : null
    if (placed && placed.isPlaced) return {}
    return { text: orgText(await read($, agents), await read($, tenantName), await read($, error)) }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const list: OrgAgent[] = await read($, agents)
    const reason = await read($, error)
    const tenant = await read($, tenantName)
    const isRestricted = await read($, restricted)
    return (
      <Box flexDirection="column">
        <Box flexDirection="row" columnGap={2}>
          <Text bold>{'Org' + (tenant ? ' for ' + tenant : '') + (isRestricted ? ' (restricted)' : '')}</Text>
          <Button key="reload" label="reload" hotkey="r" plain onPress={() => load($)} />
        </Box>
        {reason !== null && <Text color="red">{'Org unavailable: ' + reason}</Text>}
        {list.map((a) => (
          <Box flexDirection="column" key={'lane-' + a.slug}>
            {laneLines(a).map((line, i) => (
              <Text key={'lane-' + a.slug + '-' + i} bold={i === 0} dimColor={i > 0 || !a.enabled} wrap="truncate-end">{line}</Text>
            ))}
          </Box>
        ))}
      </Box>
    )
  })
}
