import { expect, mock, test } from 'claude-code/testing'

const card = (id: string, over = {}) => ({
  id, name: id, category: 'mod', kind: 'claude-mod', disposition: 'add', risk: 'low', approval: 'no', agents: [], summary: id + ' summary', enableable: true, ...over,
})
const TABLE = {
  schema: 'snowgloves.mods-catalog.v1', tenant: 'acme', enabled: ['sg-rail'],
  cards: [
    card('sg-rail'), card('sg-fleet'),
    card('lazyweb', { category: 'mcp', disposition: 'hold', risk: 'high' }),
    card('agent-reach', { category: 'skills', disposition: 'refuse', enableable: false }),
    card('a-playbook', { category: 'playbook', disposition: 'pointer', enableable: false }),
  ],
}

const PANE = {
  plugin: 'sg-catalog', component: 'Pane', requestId: 'sg-catalog', viewport: { columns: 140, rows: 40 },
  props: { title: 'Catalog', isFocused: true, bodyColumns: 100, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

function stubHost(on, { answer = 'Enable', surfaces = ['terminal'], onboardExit = 0, validateOut = '{"success":true,"contents":[]}' } = {}) {
  const runs: { argv: string[]; stdin?: string }[] = []
  const toasts: string[] = []
  mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('env.get', ($, e) => ({ value: { SNOWGLOVES_TENANT: 'acme' }[e.name] }))
  on('fs.exists', () => ({ value: false }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    runs.push({ argv: [...e.argv], stdin: e.init?.stdin })
    if (e.argv[0] === 'claude') return { value: { exitCode: 0, stdout: validateOut, stderr: '' } }
    if (e.argv.includes('draft-card')) return { value: { exitCode: 0, stdout: '{"card":"/cat/cards/evil-mod.md","flags":["I5","I6"]}', stderr: '' } }
    if (e.argv.some((a) => a.endsWith('onboard.py'))) return { value: { exitCode: onboardExit, stdout: '', stderr: onboardExit ? 'no such card\n' : '' } }
    return { value: { exitCode: 0, stdout: JSON.stringify(TABLE), stderr: '' } }
  })
  // $.ui.ask reaches Claude Code as an AskUserQuestion tool call
  on('tool.call', ($, e) => ({ result: { answers: { [e.questions[0].question]: answer } } }))
  return { runs, toasts }
}

const onboards = (runs: { argv: string[] }[]) => runs.filter((r) => r.argv.some((a) => a.endsWith('onboard.py')))

test('the pane lists cards with enable only on add cards that are not enabled, on both surfaces', async ($, on) => {
  stubHost(on)
  await $.command.run({ command: 'sg-catalog', args: '' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: 'Catalog for acme: 5 of 5 cards, 1 enabled' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'enable-sg-fleet' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'enable-sg-rail' })).toBeUndefined()
    expect(await ui.find({ type: 'Button', key: 'enable-lazyweb' })).toBeUndefined()
    expect(await ui.find({ type: 'Button', key: 'enable-agent-reach' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: 'on hold: review the card first; it is not enabled' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'refused: the platform never enables this' })).toBeDefined()
    await ui.unmount()
  }
})

test('enable asks, then runs onboard.py for the tenant', async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'sg-catalog', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'enable-sg-fleet' })
  expect(onboards(host.runs)[0].argv.slice(2)).toEqual(['--tenant', 'acme', '--enable', 'sg-fleet'])
  expect(host.toasts).toContain('Enabled sg-fleet for acme')
})

test('declining leaves the card disabled and runs nothing', async ($, on) => {
  const host = stubHost(on, { answer: 'Cancel' })
  await $.command.run({ command: 'sg-catalog', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'enable-sg-fleet' })
  expect(onboards(host.runs)).toEqual([])
  expect(await ui.find({ type: 'Text', text: 'Left sg-fleet disabled' })).toBeDefined()
})

test('a failing onboard is reported', async ($, on) => {
  stubHost(on, { onboardExit: 1 })
  await $.command.run({ command: 'sg-catalog', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'enable-sg-fleet' })
  expect(await ui.find({ type: 'Text', text: 'Could not enable sg-fleet: no such card' })).toBeDefined()
})

test('the disposition filter narrows the list', async ($, on) => {
  stubHost(on)
  await $.command.run({ command: 'sg-catalog', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.select({ key: 'filter-disposition', value: 'hold' })
  expect(await ui.find({ type: 'Text', text: 'Catalog for acme: 1 of 5 cards, 1 enabled' })).toBeDefined()
})

test('without a surface the command lists in text', async ($, on) => {
  stubHost(on, { surfaces: [] })
  const out = await $.command.run({ command: 'sg-catalog', args: '' })
  expect(out.text.split('\n').slice(0, 2)).toEqual(['Catalog for acme: 5 cards, 1 enabled', '● sg-rail  add  mod  risk low'])
})

test('/sg-mod-review validates the folder and drafts a hold card from the report', async ($, on) => {
  const host = stubHost(on)
  const out = await $.command.run({ command: 'sg-mod-review', args: '/mods/Evil Mod/' })
  expect(host.runs[0].argv).toEqual(['claude', 'plugin', 'validate', '--json', '/mods/Evil Mod/'])
  const draft = host.runs[1]
  expect(draft.argv.slice(2)).toEqual(['draft-card', '--id', 'evil-mod', '--source', '/mods/Evil Mod/'])
  expect(draft.stdin).toBe('{"success":true,"contents":[]}')
  expect(out.text).toContain('Drafted a hold card: /cat/cards/evil-mod.md. Flags: I5, I6.')
  expect(out.text).toContain('Nothing was installed or enabled')
})

test('/sg-mod-review needs a path', async ($, on) => {
  stubHost(on)
  const out = await $.command.run({ command: 'sg-mod-review', args: '  ' })
  expect(out.text).toContain('Usage')
})

test('a validate that prints no report drafts nothing', async ($, on) => {
  const host = stubHost(on, { validateOut: 'claude: not found' })
  const out = await $.command.run({ command: 'sg-mod-review', args: '/mods/x' })
  expect(out.text).toContain('Validate printed no report')
  expect(host.runs.length).toBe(1)
})
