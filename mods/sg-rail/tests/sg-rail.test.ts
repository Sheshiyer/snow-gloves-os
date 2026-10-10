import { expect, mock, test } from 'claude-code/testing'

const SNAPSHOT = {
  schema: 'snowgloves.mods-snapshot.v1',
  data_root: '/ops/snow-gloves-ops',
  data_root_source: 'env',
  tenant: 'acme',
  tenant_source: 'flag',
  tenants: ['acme'],
  approvals: { pending_total: 2, by_tenant: { acme: 2 }, items: [] },
  walk: { verdict: 'GREEN', events: 8, loops: 4, path: '/x' },
  isa: { checked: 3, total: 20 },
  endpoints: { hermes: 'http://127.0.0.1:4100', omniroute: 'http://127.0.0.1:20128' },
  warnings: ['a warning'],
}

const RAIL_UI = {
  schema: 'temperance.rail-ui.v1',
  session_id: 's1',
  rail: '♄ RAIL · NIGREDO · OBSERVE · 1/7\n  ·  mode      ALGORITHM\n  ·  combo     noesis-verify\n  ·  head      antigravity · gemini-flash',
  manifest_runtime: '☿ MANIFEST · OFFLINE\n  ·  omniroute  READY · http://127.0.0.1:20128',
  pai_mode_offer: '',
  updated_at: '2026-10-10T12:00:00Z',
}

const BAND = {
  plugin: 'sg-rail',
  component: 'AbovePrompt',
  viewport: { columns: 140, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 120, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const

// Everything the mod reaches outside itself, answered in Claude Code's place
function stubHost(on, { snapshotOut = JSON.stringify(SNAPSHOT), hermesOk = true, railFile = true } = {}) {
  const calls = { argv: [] as string[][], env: {} as Record<string, string | undefined>, toasts: [] as string[] }
  mock.clock(on)
  on('env.get', ($, e) => ({ value: { HOME: '/home/u', SNOWGLOVES_TENANT: 'acme' }[e.name] }))
  on('env.set', ($, e) => {
    calls.env[e.name] = e.value
    return { value: undefined }
  })
  on('fs.exists', ($, e) => ({ value: e.path.endsWith('.ui.json') ? railFile : false }))
  on('fs.read', () => ({ value: JSON.stringify(RAIL_UI) }))
  on('session.cwd', () => ({ value: '/work' }))
  on('session.id', () => ({ value: 's1' }))
  on('process.run', ($, e) => {
    calls.argv.push([...e.argv])
    return { value: { exitCode: snapshotOut ? 0 : 1, stdout: snapshotOut, stderr: snapshotOut ? '' : 'Traceback\nboom' } }
  })
  on('http.fetch', ($, e) => ({
    value: { status: 200, ok: e.url.includes(':4100') ? hermesOk : true, headers: {}, text: '{}' },
  }))
  on('command.register', () => ({ value: undefined }))
  on('ui.toast', ($, e) => {
    calls.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return calls
}

test('/sg runs the snapshot with the tenant and prints a summary', async ($, on) => {
  const calls = stubHost(on, { hermesOk: false })
  const answer = await $.command.run({ command: 'sg', args: '' })
  const argv = calls.argv[0]
  expect(argv[0]).toBe('python3')
  expect(argv[1].endsWith('/scripts/sg_mods.py')).toBe(true)
  expect(argv[2]).toBe('snapshot')
  expect(argv).toContain('--tenant')
  expect(argv[argv.indexOf('--tenant') + 1]).toBe('acme')
  expect(answer.text).toContain('SG acme · data snow-gloves-ops · hermes ○ · omniroute ● · approvals 2 · walk GREEN · ISA 3/20')
  expect(answer.text).toContain('♄ NIGREDO · OBSERVE · 1/7 · ALGORITHM · combo noesis-verify')
  expect(answer.text).toContain('warning: a warning')
})

test('session start asks PromptProcessing for the rail file', async ($, on) => {
  const calls = stubHost(on)
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(calls.env.TEMPERANCE_RAIL_SINK).toBe('file')
})

test('the band shows status and rail, and hides on press', async ($, on) => {
  stubHost(on)
  await $.command.run({ command: 'sg', args: '' })
  for (const surface of ['terminal', 'desktop'] as const) {
    await $.command.run({ command: 'sg', args: 'show' })
    const ui = await $.ui.mount({ ...BAND, surface })
    expect(await ui.find({ type: 'Text', text: /^SG acme · data snow-gloves-ops/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^♄ NIGREDO/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^☿ manifest offline · omniroute READY/ })).toBeDefined()
    await ui.press({ key: 'sg-hide' })
    expect(await ui.find({ type: 'Text', text: /^SG acme/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('a failed snapshot says so in the band', async ($, on) => {
  stubHost(on, { snapshotOut: '', railFile: false })
  const answer = await $.command.run({ command: 'sg', args: '' })
  expect(answer.text).toBe('Snapshot unavailable: boom')
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'SG snapshot failed: boom' })).toBeDefined()
})

test('the band stays out of the way before the first snapshot', async ($, on) => {
  stubHost(on)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'drawn by Claude Code' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^SG / })).toBeUndefined()
})

test('the approvals button runs /approvals, or says what to install', async ($, on) => {
  const calls = stubHost(on)
  let installed = false
  const ran: string[] = []
  on('command.list', () => ({ value: installed ? [{ name: 'approvals', description: '', source: 'plugin' }] : [] }))
  on('command.run', ($, e) => {
    ran.push(e.command)
    return { text: '' }
  })
  await $.command.run({ command: 'sg', args: '' })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  await ui.press({ key: 'sg-approvals' })
  expect(calls.toasts).toEqual(['Install sg-approvals for /approvals'])
  installed = true
  await ui.press({ key: 'sg-approvals' })
  expect(ran).toEqual(['approvals'])
})
