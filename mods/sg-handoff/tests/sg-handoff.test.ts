import { expect, mock, test } from 'claude-code/testing'

const PANE = {
  plugin: 'sg-handoff', component: 'Pane', requestId: 'sg-handoff', viewport: { columns: 120, rows: 40 },
  props: { title: 'Inbox', isFocused: true, bodyColumns: 80, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

function stubHost(on, { answer = 'Write', forkOk = true, delivered = true, writeOut = '{"path":"/work/.project/HANDOFF.md"}', surfaces = ['terminal'] } = {}) {
  const sent: { to: unknown; text: string }[] = []
  const submitted: string[] = []
  const toasts: string[] = []
  const runs: { argv: string[]; stdin?: string }[] = []
  mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('fs.exists', () => ({ value: false }))
  on('session.cwd', () => ({ value: '/work' }))
  on('session.id', () => ({ value: 'me-1' }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('model.fork', () => ({ value: forkOk ? { isAnswered: true, text: '## Goal\nShip mods', usage: {} } : { isAnswered: false, reason: 'nothing-to-fork', usage: {} } }))
  on('process.run', ($, e) => {
    runs.push({ argv: [...e.argv], stdin: e.init?.stdin })
    return { value: { exitCode: 0, stdout: writeOut, stderr: '' } }
  })
  on('session.send', ($, e) => {
    sent.push({ to: e.to, text: e.text })
    return delivered ? { isDelivered: true } : { isDelivered: false, reason: 'session not running' }
  })
  on('prompt.submit', ($, e) => {
    submitted.push(e.text)
    return { text: e.text }
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  // $.ui.ask reaches Claude Code as an AskUserQuestion tool call
  on('tool.call', ($, e) => ({ result: { answers: { [e.questions[0].question]: answer } } }))
  return { sent, submitted, toasts, runs }
}

test('/handoff writes the file from the model\'s handoff and tells the other session', async ($, on) => {
  const host = stubHost(on)
  const out = await $.command.run({ command: 'handoff', args: 'sess-2' })
  expect(out.text).toBe('Handoff written to /work/.project/HANDOFF.md and session sess-2 told.')
  expect(host.runs[0].argv.slice(2)).toEqual(['write-handoff', '--cwd', '/work', '--session', 'me-1'])
  expect(host.runs[0].stdin).toBe('## Goal\nShip mods')
  expect(host.sent[0].to).toBe('sess-2')
  expect(host.sent[0].text).toContain('/work/.project/HANDOFF.md')
})

test('/handoff with no session only writes the file', async ($, on) => {
  const host = stubHost(on)
  const out = await $.command.run({ command: 'handoff', args: '' })
  expect(out.text).toBe('Handoff written to /work/.project/HANDOFF.md')
  expect(host.sent).toEqual([])
})

test('cancelling writes nothing', async ($, on) => {
  const host = stubHost(on, { answer: 'Cancel' })
  const out = await $.command.run({ command: 'handoff', args: 'sess-2' })
  expect(out.text).toBe('Handoff not written (cancelled).')
  expect(host.runs).toEqual([])
  expect(host.sent).toEqual([])
})

test('nothing to fork says so and writes nothing', async ($, on) => {
  const host = stubHost(on, { forkOk: false })
  const out = await $.command.run({ command: 'handoff', args: '' })
  expect(out.text).toBe('No handoff written: nothing-to-fork')
  expect(host.runs).toEqual([])
})

test('an undelivered send is reported with its reason', async ($, on) => {
  const host = stubHost(on, { delivered: false })
  const out = await $.command.run({ command: 'handoff', args: 'sess-2' })
  expect(out.text).toContain('Not delivered to sess-2: session not running')
  expect(host.toasts[0]).toContain('session not running')
})

test('a write that fails is reported', async ($, on) => {
  stubHost(on, { writeOut: '{"error":"no .project folder"}' })
  const out = await $.command.run({ command: 'handoff', args: '' })
  expect(out.text).toBe('Handoff not written: no .project folder')
})

const FROM_PEER = { origin: { kind: 'peer' }, text: '[sg] CTO finished the graph' } as const

test('inbox off: peer messages reach Claude as before', async ($, on) => {
  stubHost(on)
  on('session.receive', ($, e) => ({ text: e.text }))
  const out = await $.session.receive(FROM_PEER)
  expect(out.text).toBe('[sg] CTO finished the graph')
})

test('inbox on: tagged peer messages are held, others pass', async ($, on) => {
  const host = stubHost(on)
  on('session.receive', ($, e) => ({ text: e.text }))
  await $.command.run({ command: 'inbox', args: 'on' })
  const held = await $.session.receive(FROM_PEER)
  expect(held.consumed).toBe('Held in /inbox')
  expect(host.toasts).toContain('Inbox: 1 message held (/inbox)')
  expect((await $.session.receive({ origin: { kind: 'peer' }, text: 'hello' })).text).toBe('hello')
  expect((await $.session.receive({ origin: { kind: 'bridge' }, text: '[sg] x' })).text).toBe('[sg] x')
})

test('the pane lists held messages; hand to Claude submits one, dismiss drops one', async ($, on) => {
  const host = stubHost(on)
  on('session.receive', ($, e) => ({ text: e.text }))
  await $.command.run({ command: 'inbox', args: 'on' })
  await $.session.receive(FROM_PEER)
  await $.session.receive({ origin: { kind: 'peer' }, text: '[sg] second' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: 'Inbox is on: 2 held' })).toBeDefined()
    await ui.unmount()
  }
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'hand-1' })
  expect(host.submitted).toEqual(['CTO finished the graph'])
  await ui.press({ key: 'drop-2' })
  expect(await ui.find({ type: 'Text', text: 'Inbox is on: 0 held' })).toBeDefined()
  expect(host.submitted.length).toBe(1)
})

test('without a surface /inbox lists in text', async ($, on) => {
  stubHost(on, { surfaces: [] })
  const out = await $.command.run({ command: 'inbox', args: '' })
  expect(out.text).toBe('Inbox is off: 0 held')
})
