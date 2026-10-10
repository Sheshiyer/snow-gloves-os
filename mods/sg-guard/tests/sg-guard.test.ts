import { expect, test, tier } from 'claude-code/testing'

tier('prepend')

const SERVER = '6e66be5a-d0cb-4df1-8fd4-bbfaf77c8604'

function stubHost(on, { cards = '["sg-rail"]', result = 'ran' } = {}) {
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('fs.exists', () => ({ value: false }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: cards, stderr: '' } }))
  // The tool itself, reached only when the guard passes the call on
  on('tool.call', () => ({ result, text: result }))
}

async function start($) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
}

const ERP = 'mcp__' + SERVER + '__'

test('other servers and built-in tools go on untouched', async ($, on) => {
  stubHost(on)
  await start($)
  expect((await $.tool.call({ tool: 'Bash', command: 'ls' })).result).toBe('ran')
  expect((await $.tool.call({ tool: 'mcp__github__search', q: 'x' })).result).toBe('ran')
})

test('every ERP tool but the read tool is refused', async ($, on) => {
  stubHost(on)
  await start($)
  for (const name of ['upsert_client', 'record_count', 'delete_order', 'send_invoice']) {
    const out = await $.tool.call({ tool: ERP + name })
    expect(out.deny).toContain('is not permitted')
  }
})

test('a bounded ids-only SELECT passes', async ($, on) => {
  stubHost(on)
  await start($)
  const out = await $.tool.call({ tool: ERP + 'execute_read_only_query', query: 'SELECT cli_id FROM TM_CLI_CLient LIMIT 10' })
  expect(out.result).toBe('ran')
})

test('writes, comments, stacked statements and locks are refused', async ($, on) => {
  stubHost(on)
  await start($)
  const bad = [
    'UPDATE TM_CLI_CLient SET cli_id = 1',
    'SELECT cli_id FROM TM_CLI_CLient; DROP TABLE x',
    'SELECT cli_id FROM TM_CLI_CLient -- hi',
    'SELECT cli_id FROM TM_CLI_CLient FOR UPDATE',
    'DELETE FROM TM_CLI_CLient',
    'SELECT cli_id FROM TM_CLI_CLient LIMIT 500',
  ]
  for (const query of bad) {
    const out = await $.tool.call({ tool: ERP + 'execute_read_only_query', query })
    expect(out.deny).toContain('ERP read-only guard')
  }
})

test('personal columns, never-touch tables and SELECT * are refused', async ($, on) => {
  stubHost(on)
  await start($)
  for (const query of [
    'SELECT cli_email FROM TM_CLI_CLient',
    'SELECT cli_id FROM TR_BAC_Bank_Account',
    'SELECT cli_id FROM TM_MAK_Mcp_Api_Key',
    'SELECT * FROM TM_CLI_CLient',
    'SELECT c.* FROM TM_CLI_CLient c',
  ]) {
    const out = await $.tool.call({ tool: ERP + 'execute_read_only_query', query })
    expect(out.deny).toContain('ERP read-only guard')
  }
})

test('a missing query is refused', async ($, on) => {
  stubHost(on)
  await start($)
  const out = await $.tool.call({ tool: ERP + 'execute_read_only_query' })
  expect(out.deny).toContain('needs a query string')
})

test('MCP results lose emails and phone numbers', async ($, on) => {
  stubHost(on, { result: 'write to jean@example.fr or +33 1 23 45 67 89' })
  await start($)
  const out = await $.tool.call({ tool: 'mcp__github__get', q: 'x' })
  expect(out.text).toBe('write to [email] or [phone]')
  expect(out.result).toBe('write to [email] or [phone]')
})

test('built-in tool results are left alone', async ($, on) => {
  stubHost(on, { result: 'jean@example.fr' })
  await start($)
  expect((await $.tool.call({ tool: 'Bash', command: 'echo' })).result).toBe('jean@example.fr')
})

test('redaction can be turned off', { options: { redactResults: false } }, async ($, on) => {
  stubHost(on, { result: 'jean@example.fr' })
  await start($)
  expect((await $.tool.call({ tool: 'mcp__github__get' })).result).toBe('jean@example.fr')
})

test('a quiet user mod loads under the supply-chain check', {
  plugins: [{ name: 'calm', register: (on) => { on('command.run', { command: 'calm' }, () => ({ text: 'calm ran' })) } }],
}, async ($, on) => {
  stubHost(on)
  await start($)
  expect((await $.command.run({ command: 'calm', args: '' })).text).toBe('calm ran')
})

test('/sg-guard reports what it refused', async ($, on) => {
  stubHost(on)
  await start($)
  await $.tool.call({ tool: ERP + 'upsert_client' })
  const out = await $.command.run({ command: 'sg-guard', args: '' })
  expect(out.text).toContain('1 call(s) refused')
})
