// sg-guard: three guards that stay in force whatever the model or another mod does.
//   1. The ERP connector may only run execute_read_only_query, one bounded ids-only SELECT. A call is
//      refused with { deny } or passed on with next(e); this mod never answers one, so the settings
//      PreToolUse hook (erp-read-only.py) still runs after it.
//   2. Results of MCP tools lose emails, phone numbers, card numbers and secrets before the model reads them.
//   3. plugin.register refuses user-tier mods that spawn or fetch without a catalog card. Claude Code only
//      asks this hook about mods that load after it, so it is effective when sg-guard is in prependPlugins.
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import { READ_TOOL, erpProblem, redact, supplyProblem } from './lib'

const CARDS_TIMEOUT_MS = 15_000

let addCards: ReadonlySet<string> = new Set()
let blocked = 0
let redacted = 0
const refused: string[] = []

async function loadCards($: EngineInterface, options: PluginOptions) {
  try {
    const root = String(options.platformRoot || '') || $.plugin.root.split('/').slice(0, -2).join('/')
    const venv = root + '/.venv/bin/python'
    const python = (await $.fs.exists(venv)) ? venv : 'python3'
    const run = await $.process.run([python, root + '/scripts/sg_mods.py', 'cards-add'], { cwd: root, timeoutMs: CARDS_TIMEOUT_MS })
    const names = JSON.parse(run.stdout)
    if (Array.isArray(names)) addCards = new Set(names.map(String))
  } catch {
    // keep the last list; with none, every risky user mod is refused
  }
}

// register sets these from the plugin's options
let serverId = ''
let redactResults = true
let supplyChain = true
let pluginOptions: PluginOptions = {}

async function erpGuard($: EngineInterface, e, next) {
  const problem = erpProblem(e.tool, serverId, e.query)
  if (problem) {
    blocked += 1
    return { deny: 'ERP read-only guard: ' + problem }
  }
  return next(e)
}

async function redactor($: EngineInterface, e, next) {
  const res = await next(e)
  if (!redactResults || !res || res.deny) return res
  const tally = { n: 0 }
  const clean = { ...res, result: redact(res.result, tally), text: redact(res.text, tally) }
  redacted += tally.n
  return tally.n ? clean : res
}

function statusText() {
  return [
    'sg-guard',
    '  ERP server ' + (serverId || '(unset)') + ': only ' + READ_TOOL + ' passes; ' + blocked + ' call(s) refused this session',
    '  redaction ' + (redactResults ? 'on' : 'off') + ': ' + redacted + ' value(s) replaced',
    '  supply chain ' + (supplyChain ? 'on' : 'off') + ' (' + addCards.size + ' add cards): refused ' + (refused.join(', ') || 'none'),
    '  Mods only reach plugin.register when sg-guard is listed in prependPlugins (managed settings, or user settings on a machine with none).',
  ].join('\n')
}

export const register: Register = (on, options) => {
  pluginOptions = options
  serverId = String(options.erpServerId ?? '')
  redactResults = options.redactResults !== false
  supplyChain = options.supplyChain !== false

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'sg-guard', description: 'Show what the Snow Gloves guard has refused this session', immediate: true })
    if (supplyChain) await loadCards($, pluginOptions)
    return next(e)
  })

  // Fails closed for the ERP server only: a failure on someone else's server lets it go on
  on('tool.call', { tool: /^mcp__/ }, erpGuard).catch(($, e, next) => {
    if (next.called) return next(e)
    return serverId && e.tool.startsWith('mcp__' + serverId + '__') ? { deny: 'ERP read-only guard could not check this call, refusing' } : next(e)
  })

  on('tool.call', { tool: /^mcp__/ }, redactor).catch(($, e, next) => (next.called ? next(e) : { deny: 'sg-guard redaction could not run, refusing' }))

  on('plugin.register', ($, e, next) => {
    if (!supplyChain || e.name === 'sg-guard') return next(e)
    const why = supplyProblem(e.name, e.provenance, e.uses, addCards)
    if (why) {
      refused.push(e.name)
      return { refuse: 'sg-guard: ' + why }
    }
    return next(e)
  })

  on('command.run', { command: 'sg-guard' }, () => ({ text: statusText() }))
}
