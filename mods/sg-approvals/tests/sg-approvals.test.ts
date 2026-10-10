import { expect, mock, test } from 'claude-code/testing'

const ticket = (id: string, over = {}) => ({
  tenant: 'acme', id, connector: 'gmail', capability: 'gmail.send_message', kind: '', risk: 'medium',
  created_at: 0, payload_keys: ['to'], ...over,
})

const PANE = {
  plugin: 'sg-approvals',
  component: 'Pane',
  requestId: 'sg-approvals',
  viewport: { columns: 120, rows: 40 },
  props: {
    title: 'Approvals', isFocused: true, bodyColumns: 80, placement: 'inline',
    scroll: { offset: 0, bodyRows: 20 }, view: {},
  },
} as const

// A host whose snapshot lists `state.items`, and that records every process the mod starts
function stubHost(on, { answer = 'Approve', placed = true, surfaces = ['terminal'] } = {}) {
  const state = { items: [ticket('APR-1'), ticket('APR-2', { risk: 'high', connector: 'xmcp', capability: 'post' })] }
  const runs: string[][] = []
  const toasts: string[] = []
  const clock = mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('env.get', ($, e) => ({ value: { SNOWGLOVES_ACTOR: 'founder', USER: 'axio' }[e.name] }))
  on('fs.exists', () => ({ value: false }))
  on('session.cwd', () => ({ value: '/work' }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: placed ? { isPlaced: true } : { isPlaced: false, reason: 'no surface' } }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    runs.push([...e.argv])
    if (e.argv.includes('snapshot')) {
      const snap = { schema: 'snowgloves.mods-snapshot.v1', approvals: { pending_total: state.items.length, items: state.items } }
      return { value: { exitCode: 0, stdout: JSON.stringify(snap), stderr: '' } }
    }
    const id = e.argv[e.argv.indexOf('--id') + 1]
    state.items = state.items.filter((t) => t.id !== id)
    return { value: { exitCode: 0, stdout: JSON.stringify({ ok: true, ticket: { id } }), stderr: '' } }
  })
  // $.ui.ask reaches Claude Code as an AskUserQuestion tool call
  on('tool.call', ($, e) => ({ result: { answers: { [e.questions[0].question]: answer } } }))
  return { state, runs, toasts, clock }
}

const decisions = (runs: string[][]) => runs.filter((argv) => argv.some((a) => a.endsWith('/scripts/approvals.py')))

test('/approvals lists tickets with payload keys, on both surfaces', async ($, on) => {
  stubHost(on)
  await $.command.run({ command: 'approvals', args: '' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: 'Pending approvals: 2' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /acme · gmail\.send_message · risk medium · 0m · payload: to/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^! acme · xmcp\.post · risk high/ })).toBeDefined()
    await ui.unmount()
  }
})

test('approve runs approvals.py with the actor', async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'approvals', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'approve-APR-1' })
  const argv = decisions(host.runs)[0]
  expect(argv.slice(2)).toEqual(['approve', '--tenant', 'acme', '--id', 'APR-1', '--actor', 'founder'])
  expect(await ui.find({ type: 'Text', text: 'Approved APR-1 as founder' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Pending approvals: 1' })).toBeDefined()
})

test('a high-risk approve asks first', async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'approvals', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'approve-APR-2' })
  expect(decisions(host.runs)[0]).toContain('APR-2')
})

test('a high-risk approve the user does not confirm stays pending', async ($, on) => {
  const host = stubHost(on, { answer: 'Keep pending' })
  await $.command.run({ command: 'approvals', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'approve-APR-2' })
  expect(decisions(host.runs)).toEqual([])
  expect(await ui.find({ type: 'Text', text: 'Left APR-2 pending' })).toBeDefined()
})

test('reject records a reason and needs no confirmation', async ($, on) => {
  const host = stubHost(on, { answer: 'Keep pending' })
  await $.command.run({ command: 'approvals', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'reject-APR-2' })
  const argv = decisions(host.runs)[0]
  expect(argv.slice(2, 4)).toEqual(['reject', '--tenant'])
  expect(argv).toContain('--reason')
})

test('the data root option reaches both scripts', { options: { dataRoot: '/ops' } }, async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'approvals', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'approve-APR-1' })
  for (const argv of host.runs) expect(argv.slice(-2)).toEqual(['--data-root', '/ops'])
})

test('the timer toasts new tickets but not the first look', async ($, on) => {
  const host = stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await host.clock.settle()
  expect(host.toasts).toEqual([])
  host.state.items = [...host.state.items, ticket('APR-3')]
  await host.clock.advance(30_000)
  expect(host.toasts).toEqual(['1 new approval waiting: /approvals'])
})

test('a pane that waits undrawn falls back to text', async ($, on) => {
  stubHost(on, { placed: false })
  const answer = await $.command.run({ command: 'approvals', args: '' })
  expect(answer.text).toContain('APR-1  acme')
})

test('in a plain claude -p run, /approvals answers in text', async ($, on) => {
  stubHost(on, { surfaces: [] })
  const answer = await $.command.run({ command: 'approvals', args: '' })
  expect(answer.text).toContain('Pending approvals:')
  expect(answer.text).toContain('APR-2  acme · xmcp.post · risk high')
  expect(answer.text).not.toContain('x@y.io')
})
