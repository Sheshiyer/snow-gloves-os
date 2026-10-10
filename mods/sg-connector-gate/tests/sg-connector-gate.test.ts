import { expect, mock, test } from 'claude-code/testing'

const server = (over = {}) => ({
  category: 'mcp', disposition: 'add', risk: 'medium', approval: 'no', enabled: true, needs_approval: false, ...over,
})

const TABLE = {
  schema: 'snowgloves.mods-gate.v1',
  tenant: 'acme',
  data_root: '/ops',
  ttl_hours: 24,
  managed: ['figma-mcp', 'github-mcp', 'lazyweb', 'awesome-mcp-servers', 'xmcp'],
  servers: {
    'github-mcp': server(),
    'figma-mcp': server({ enabled: false }),
    lazyweb: server({ disposition: 'hold', approval: 'yes' }),
    'awesome-mcp-servers': server({ disposition: 'refuse' }),
    xmcp: server({ risk: 'high', approval: 'yes', needs_approval: true }),
  },
  grants: [{ connector: 'xmcp', capability: 'search', id: 'APR-ok', decided_at: 1 }],
  pending: [],
}

// Answers what Claude Code would, and records the bridge calls the gate makes
function stubHost(on, { tenant = 'acme', table = TABLE, ticketFails = false } = {}) {
  const runs: string[][] = []
  const logs: string[] = []
  mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('env.get', ($, e) => ({ value: e.name === 'SNOWGLOVES_TENANT' ? tenant : undefined }))
  on('fs.exists', () => ({ value: false }))
  on('process.run', ($, e) => {
    runs.push([...e.argv])
    if (e.argv.includes('gate-table')) return { value: { exitCode: 0, stdout: JSON.stringify(table), stderr: '' } }
    if (ticketFails) return { deny: 'python is gone' }
    return { value: { exitCode: 0, stdout: JSON.stringify({ ticket: { id: 'APR-9-abc' }, deduped: false }), stderr: '' } }
  })
  on('ui.log', ($, e) => {
    logs.push(e.text)
    return { value: undefined }
  })
  on('ui.toast', () => ({ value: undefined }))
  // The tool itself, reached only when the gate passes the call on
  on('tool.call', () => ({ result: 'ran' }))
  return { runs, logs }
}

async function start($) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
}

test('an MCP server the catalog does not manage goes on untouched', async ($, on) => {
  stubHost(on)
  await start($)
  const out = await $.tool.call({ tool: 'mcp__6e66be5a__execute_read_only_query', sql: 'select 1' })
  expect(out).toEqual({ result: 'ran' })
  expect(await $.tool.call({ tool: 'Bash', command: 'ls' })).toEqual({ result: 'ran' })
})

test('enabled, low-risk servers run', async ($, on) => {
  stubHost(on)
  await start($)
  expect(await $.tool.call({ tool: 'mcp__github-mcp__search_issues', q: 'x' })).toEqual({ result: 'ran' })
})

test('hold and refuse cards never run', async ($, on) => {
  stubHost(on)
  await start($)
  const held = await $.tool.call({ tool: 'mcp__lazyweb__fetch' })
  expect(held.deny).toContain('lazyweb is on hold')
  const refused = await $.tool.call({ tool: 'mcp__awesome-mcp-servers__list' })
  expect(refused.deny).toContain('refused')
})

test('a server the tenant has not enabled is refused with the enable command', async ($, on) => {
  stubHost(on)
  await start($)
  const out = await $.tool.call({ tool: 'mcp__figma-mcp__get_file' })
  expect(out.deny).toContain('python3 scripts/onboard.py --tenant acme --enable figma-mcp')
})

test('a high-risk tool without a grant queues a ticket and is refused', async ($, on) => {
  const host = stubHost(on)
  await start($)
  const out = await $.tool.call({ tool: 'mcp__xmcp__post_tweet', text: 'hi' })
  expect(out.deny).toContain('Ticket APR-9-abc is queued')
  const request = host.runs.find((argv) => argv.includes('request-approval'))
  expect(request.slice(2)).toEqual([
    'request-approval', '--tenant', 'acme', '--connector', 'xmcp', '--capability', 'post_tweet', '--tool', 'mcp__xmcp__post_tweet',
  ])
})

test('a granted high-risk tool runs', async ($, on) => {
  stubHost(on)
  await start($)
  expect(await $.tool.call({ tool: 'mcp__xmcp__search', q: 'x' })).toEqual({ result: 'ran' })
})

test('when the ticket cannot be queued the gate fails closed', async ($, on) => {
  stubHost(on, { ticketFails: true })
  await start($)
  const out = await $.tool.call({ tool: 'mcp__xmcp__post_tweet' })
  expect(out.deny).toContain('could not check xmcp')
  expect(out.deny).toContain('did not run')
})

test('observe mode logs and lets every call through', { options: { gateMode: 'observe' } }, async ($, on) => {
  const host = stubHost(on)
  await start($)
  expect(await $.tool.call({ tool: 'mcp__lazyweb__fetch' })).toEqual({ result: 'ran' })
  expect(host.logs.some((line) => line.startsWith('would refuse mcp__lazyweb__fetch'))).toBe(true)
})

test('with no tenant the gate only observes', async ($, on) => {
  const host = stubHost(on, { tenant: '' })
  await start($)
  expect(await $.tool.call({ tool: 'mcp__lazyweb__fetch' })).toEqual({ result: 'ran' })
  expect(host.runs.length).toBe(0)
  const status = await $.command.run({ command: 'sg-gate', args: '' })
  expect(status.text.startsWith('observing only (no tenant')).toBe(true)
})

test('/sg-gate lists each managed server', async ($, on) => {
  stubHost(on)
  await start($)
  const status = await $.command.run({ command: 'sg-gate', args: 'status' })
  expect(status.text.startsWith('enforce for tenant acme')).toBe(true)
  expect(status.text).toContain('figma-mcp: not enabled')
  expect(status.text).toContain('xmcp: enabled, approval per tool')
  expect(status.text).toContain('approved: xmcp.search')
})
