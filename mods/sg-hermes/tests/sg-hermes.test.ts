import { expect, mock, test } from 'claude-code/testing'

const ev = (ts: string, title: string, agents: string[] = ['interpreter']) => ({
  ts, kind: 'e2e-test', task: { title }, routing: agents.map((agent) => ({ agent, hook: 'h', skills: [], matched_glob: '*' })),
})

const PANE = {
  plugin: 'sg-hermes', component: 'Pane', requestId: 'sg-hermes', viewport: { columns: 120, rows: 40 },
  props: { title: 'Hermes', isFocused: true, bodyColumns: 80, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

function stubHost(on, { up = true, surfaces = ['terminal'] } = {}) {
  const state = { events: [ev('2026-10-10T10:00:00+00:00', 'launch referral')], posts: [] as { url: string; body: string }[], urls: [] as string[] }
  const runs: string[][] = []
  const clock = mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('env.get', ($, e) => ({ value: { SNOWGLOVES_TENANT: 'acme' }[e.name] }))
  on('fs.exists', () => ({ value: false }))
  on('session.cwd', () => ({ value: '/work' }))
  on('session.id', () => ({ value: 'sess-1' }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('process.run', ($, e) => {
    runs.push([...e.argv])
    if (e.argv.includes('snapshot')) return { value: { exitCode: 0, stdout: JSON.stringify({ endpoints: { hermes: 'http://hermes.test:4100' } }), stderr: '' } }
    const rows = [
      { ts: '2026-10-10T10:00:00+00:00', task: { title: 'launch referral' }, before: [{ agent: 'interpreter' }], after: [{ agent: 'dispatcher' }], changed: true },
      { ts: '2026-10-10T10:01:00+00:00', task: { title: 'same' }, before: [], after: [], changed: false },
    ]
    return { value: { exitCode: 0, stdout: JSON.stringify(rows), stderr: '' } }
  })
  on('http.fetch', ($, e) => {
    state.urls.push(e.url)
    if (!up) return { value: { status: 503, ok: false, headers: {}, text: '{}' } }
    if (e.init && e.init.method === 'POST') {
      state.posts.push({ url: e.url, body: String(e.init.body) })
      if (e.url.endsWith('/test/e2e')) {
        const routing = [{ agent: 'dispatcher', hook: 'virality', skills: ['growth'], matched_glob: '*referral*' }]
        return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify({ ok: true, routing }) } }
      }
      return { value: { status: 200, ok: true, headers: {}, text: '{"accepted":true}' } }
    }
    return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify({ count: state.events.length, events: state.events }) } }
  })
  return { state, runs, clock }
}

test('the live tab lists events on both surfaces, from the endpoint the snapshot reports', async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'hermes', args: '' })
  expect(host.state.urls[0]).toBe('http://hermes.test:4100/events')
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: '1 events' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /10:00:00 {2}e2e-test {2}launch referral {2}-> interpreter/ })).toBeDefined()
    await ui.unmount()
  }
})

test('the option overrides the snapshot', { options: { hermesUrl: 'http://other:9/' } }, async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'hermes', args: '' })
  expect(host.state.urls[0]).toBe('http://other:9/events')
  expect(host.runs.some((argv) => argv.includes('snapshot'))).toBe(false)
})

test('the poll asks only for events newer than the last it holds', async ($, on) => {
  const host = stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await host.clock.settle()
  host.state.events = [...host.state.events, ev('2026-10-10T10:00:05+00:00', 'second')]
  await host.clock.advance(5_000)
  expect(host.state.urls.at(-1)).toBe('http://hermes.test:4100/events?since=2026-10-10T10%3A00%3A00%2B00%3A00')
})

test('Hermes down says so', async ($, on) => {
  stubHost(on, { up: false, surfaces: [] })
  const out = await $.command.run({ command: 'hermes', args: '' })
  expect(out.text).toBe('Hermes: Hermes answered 503')
})

test('the route tab posts the title and shows the route', async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'hermes', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-route' })
  await ui.input({ key: 'route-title', text: 'launch a referral program' })
  expect(JSON.parse(host.state.posts[0].body).task.title).toBe('launch a referral program')
  expect(host.state.posts[0].url).toBe('http://hermes.test:4100/test/e2e')
  expect(await ui.find({ type: 'Text', text: 'dispatcher via virality (*referral*) skills: growth' })).toBeDefined()
})

test('the replay tab runs replay.py and lists only changed routes', async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'hermes', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'tab-replay' })
  const argv = host.runs.find((a) => a.some((x) => x.endsWith('replay.py')))
  expect(argv.slice(-2)).toEqual(['--last', '20'])
  expect(await ui.find({ type: 'Text', text: '2 replayed, 1 would route differently' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /launch referral {2}interpreter -> dispatcher/ })).toBeDefined()
})

const COMPLETE = { answer: 'ok', durationMs: 1200, isAborted: false, turnId: 't1', reason: 'answer', usage: { model: 'm', input_tokens: 1, output_tokens: 2, cache_read_input_tokens: 3, cache_creation_input_tokens: 4 } } as const

test('turns are not published unless asked', async ($, on) => {
  const host = stubHost(on)
  on('turn.complete', () => ({ text: '' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(COMPLETE)
  expect(host.state.posts).toEqual([])
})

test('with publishTurns a finished turn posts a claude.turn event', { options: { publishTurns: true } }, async ($, on) => {
  const host = stubHost(on)
  on('turn.complete', () => ({ text: '' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.complete(COMPLETE)
  await host.clock.settle()
  const body = JSON.parse(host.state.posts[0].body)
  expect(host.state.posts[0].url).toBe('http://hermes.test:4100/publish')
  expect(body.event).toEqual({ kind: 'claude.turn', session: 'sess-1', durationMs: 1200, usage: COMPLETE.usage, tenant: 'acme' })
})
