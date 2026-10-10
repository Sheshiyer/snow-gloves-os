// sg-connector-gate: skills/connector-gate as code. Before Claude calls a tool on an MCP server
// that the Snow Gloves catalog manages, it checks the card's disposition, the tenant's
// enabled.yaml, and the approvals queue, and refuses the call when they say no.
//
// It only ever passes a call on with next(e) or refuses it with { deny }. It never answers a
// call with a result, so the settings PreToolUse hooks (erp-read-only.py) still run after it.
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { GateTable } from '../types'
import { approvalReason, asGateTable, decide, platformRootFrom, splitTool, statusText } from './lib'

const RELOAD_MS = 60_000
const TABLE_TIMEOUT_MS = 15_000

// The gate decides from this copy, so a call never waits on a process start.
// session.start loads it again after every reload of the module.
let table: GateTable | null = null
let loadError: string | null = null
// register sets these from the plugin's options
let pluginOptions: PluginOptions = {}
let mode: 'enforce' | 'observe' = 'enforce'

async function settingsOf($: EngineInterface, options: PluginOptions) {
  const root = String(options.platformRoot || '') || platformRootFrom($.plugin.root)
  const tenant = String(options.tenant || '') || (await $.env.get('SNOWGLOVES_TENANT')) || ''
  const dataRoot = String(options.dataRoot || '') || (await $.env.get('SNOWGLOVES_DATA')) || ''
  const venv = root + '/.venv/bin/python'
  const python = (await $.fs.exists(venv)) ? venv : 'python3'
  const mode = options.gateMode === 'observe' ? 'observe' : 'enforce'
  const ttlHours = Number(options.ttlHours) > 0 ? Number(options.ttlHours) : 24
  return { root, tenant, dataRoot, python, mode, ttlHours }
}

function bridge(cfg: { root: string; python: string; dataRoot: string }, args: string[]): string[] {
  const argv = [cfg.python, cfg.root + '/scripts/sg_mods.py', ...args]
  if (cfg.dataRoot) argv.push('--data-root', cfg.dataRoot)
  return argv
}

// Never rejects: it runs from a timer. A failed reload keeps the last good table.
async function load($: EngineInterface, options: PluginOptions) {
  try {
    const cfg = await settingsOf($, options)
    if (!cfg.tenant) {
      table = null
      loadError = 'no tenant: set SNOWGLOVES_TENANT or the tenant option'
      return
    }
    const argv = bridge(cfg, ['gate-table', '--tenant', cfg.tenant, '--ttl-hours', String(cfg.ttlHours)])
    const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: TABLE_TIMEOUT_MS })
    const next = asGateTable(run.stdout)
    if (next) {
      table = next
      loadError = null
    } else {
      loadError = run.stdout.trim() || run.stderr.trim().split('\n').pop() || 'exit ' + run.exitCode
    }
  } catch (err) {
    loadError = String(err instanceof Error ? err.message : err)
  }
}

async function requestApproval($: EngineInterface, options: PluginOptions, connector: string, capability: string, tool: string) {
  const cfg = await settingsOf($, options)
  const argv = bridge(cfg, [
    'request-approval', '--tenant', cfg.tenant, '--connector', connector, '--capability', capability, '--tool', tool,
  ])
  const run = await $.process.run(argv, { cwd: cfg.root, timeoutMs: TABLE_TIMEOUT_MS })
  const out = JSON.parse(run.stdout)
  if (run.exitCode !== 0 || !out.ticket || !out.ticket.id) throw new Error(out.error || 'request-approval failed')
  return String(out.ticket.id)
}

async function gate($: EngineInterface, e, next) {
  const decision = decide(table, e.tool)
  if (decision.kind === 'pass') return next(e)
  if (mode === 'observe') {
    $.ui.log('would refuse ' + e.tool + (decision.kind === 'deny' ? ': ' + decision.reason : ': needs approval'))
    return next(e)
  }
  if (decision.kind === 'deny') return { deny: decision.reason }
  const ticket = await requestApproval($, pluginOptions, decision.connector, decision.capability, e.tool)
  $.ui.toast('Approval needed: ' + decision.connector + '.' + decision.capability)
  return { deny: approvalReason(e.tool, table ? table.tenant : '', ticket) }
}

export const register: Register = (on, options) => {
  pluginOptions = options
  mode = options.gateMode === 'observe' ? 'observe' : 'enforce'

  on('session.start', async ($, e, next) => {
    // Waited for, so the table is in place before Claude's first tool call
    await load($, options)
    if (!table) $.ui.log('observing only: ' + loadError)
    $.clock.every(RELOAD_MS, () => load($, options))
    await $.command.register({
      name: 'sg-gate',
      description: 'Snow Gloves connector gate: which managed MCP servers may run',
      argumentHint: '[status|reload]',
      immediate: true,
    })
    return next(e)
  })

  // Fails closed for managed servers only: a failure on someone else's server lets it go on
  on('tool.call', { tool: /^mcp__/ }, gate).catch(($, e, next) => {
    if (next.called) return next(e)
    const decision = decide(table, e.tool)
    if (decision.kind === 'pass' || mode === 'observe') return next(e)
    const parts = splitTool(e.tool)
    return {
      deny:
        'sg-connector-gate could not check ' + (parts ? parts.server : e.tool) +
        ' (' + next.error.kind + '), so the call did not run.',
    }
  })

  on('command.run', { command: 'sg-gate' }, async ($, e) => {
    if (e.args.trim() === 'reload') await load($, options)
    return { text: statusText(table, mode, loadError) }
  })
}
