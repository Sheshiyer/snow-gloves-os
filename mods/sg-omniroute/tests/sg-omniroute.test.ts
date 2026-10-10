import { expect, mock, test } from 'claude-code/testing'

const COMBOS = {
  schema: 'snowgloves.mods-combos.v1',
  combos: [
    { name: 'noesis-build', strategy: 'round-robin', members: ['a/x', 'b/y'] },
    { name: 'noesis-verify', strategy: 'priority', members: ['c/z'] },
  ],
}

const PANE = (requestId: string) => ({
  plugin: 'sg-omniroute', component: 'Pane', requestId, viewport: { columns: 120, rows: 40 },
  props: { title: 'x', isFocused: true, bodyColumns: 80, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
}) as const

const BAND = {
  plugin: 'sg-omniroute', component: 'AbovePrompt', viewport: { columns: 140, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 120, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const

function stubHost(on, { surfaces = ['terminal'], combosOut = JSON.stringify(COMBOS) } = {}) {
  const runs: string[][] = []
  mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('fs.exists', () => ({ value: false }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.usage', () => ({
    value: { startedAt: 0, context: { window: 200000, percent: 41.6 }, rateLimits: [{ kind: 'five_hour', percentUsed: 12 }], cost: { usd: 0.314 } },
  }))
  on('process.run', ($, e) => {
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: combosOut, stderr: '' } }
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  // The model request itself: a step that cost tokens
  on('turn.step', async function* ($, e) {
    return {
      turnId: e.turnId, index: e.index, answer: 'ok', toolUses: [],
      usage: { model: e.agentId ? 'noesis-verify' : 'noesis-build', input_tokens: 100, output_tokens: 50, cache_read_input_tokens: 700, cache_creation_input_tokens: 200 },
    }
  })
  return { runs }
}

const step = (index: number, agentId?: string) => ({ turnId: 't1', index, model: 'claude-x', messageCount: 3, ...(agentId ? { agentId } : {}) })

async function drain($, input) {
  // The stream's last value is the step's result
  const stream = $.turn.step(input)
  let r = await stream.next()
  while (!r.done) r = await stream.next()
  return r.value
}

test('each request is recorded, main and subagent apart, and the meter reads the session', async ($, on) => {
  stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const result = await drain($, step(0))
  expect(result.answer).toBe('ok')
  await drain($, step(1, 'sub-1'))
  await $.command.run({ command: 'omniroute', args: '' })
  const ui = await $.ui.mount({ ...PANE('sg-omniroute'), surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'OmniRoute ledger: 2 requests' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /noesis-build {2}1 req {2}in 100/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^sub-1 {2}noesis-verify/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^main {2}noesis-build/ })).toBeDefined()
})

test('the band shows context, limits, cache share and cost, on both surfaces', async ($, on) => {
  stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await drain($, step(0))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    expect(await ui.find({ type: 'Text', text: 'omniroute · ctx 42% · five_hour 12% · cache 70% · $0.31' })).toBeDefined()
    await ui.unmount()
  }
})

test('before any request the band stays out of the way', async ($, on) => {
  stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /omniroute/ })).toBeUndefined()
})

test('/combo lists the combos from the read-only database call', async ($, on) => {
  const host = stubHost(on, { surfaces: [] })
  const out = await $.command.run({ command: 'combo', args: '' })
  expect(out.text).toBe('noesis-build  round-robin  2 members: a/x, b/y\nnoesis-verify  priority  1 members: c/z')
  expect(host.runs[0].slice(-1)).toEqual(['combos'])
})

test('the database option reaches the bridge', { options: { combosDb: '/db/storage.sqlite' } }, async ($, on) => {
  const host = stubHost(on, { surfaces: [] })
  await $.command.run({ command: 'combo', args: '' })
  expect(host.runs[0].slice(-2)).toEqual(['--db', '/db/storage.sqlite'])
})

test('a combo list that cannot be read says why', async ($, on) => {
  stubHost(on, { surfaces: [], combosOut: '{"error": "no OmniRoute database"}' })
  const out = await $.command.run({ command: 'combo', args: '' })
  expect(out.text).toContain('Combos unavailable')
})
