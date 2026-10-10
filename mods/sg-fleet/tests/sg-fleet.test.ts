import { expect, mock, test } from 'claude-code/testing'

const check = (name: string, ok: boolean, critical = false) => ({ name, ok, detail: name + ' detail', critical })
const GATEWAY = [
  'gateway: https://gw.example',
  '  claude    FLEET base=https://gw.example  file=/h/.claude/settings.json',
  '  codex     NOT-FLEET base=http://coding-mac:20128/v1  file=/h/.codex/config.toml',
].join('\n')

const PANE = {
  plugin: 'sg-fleet', component: 'Pane', requestId: 'sg-fleet', viewport: { columns: 120, rows: 40 },
  props: { title: 'Fleet', isFocused: true, bodyColumns: 80, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

function stubHost(on, { surfaces = ['terminal'], broken = false } = {}) {
  const state = { checks: [check('wing', true), check('gateway', true, true), check('tailscale', false)] }
  const runs: string[][] = []
  const toasts: string[] = []
  const clock = mock.clock(on)
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('env.get', () => ({ value: undefined }))
  on('fs.exists', () => ({ value: false }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    runs.push([...e.argv])
    if (broken && e.argv.some((a) => a.endsWith('doctor.py'))) return { value: { exitCode: 1, stdout: 'nope', stderr: 'boom\ntrace' } }
    const out = e.argv.some((a) => a.endsWith('doctor.py')) ? JSON.stringify(state.checks) : GATEWAY
    return { value: { exitCode: 0, stdout: out, stderr: '' } }
  })
  return { state, runs, toasts, clock }
}

test('/fleet shows checks and surfaces on both surfaces', async ($, on) => {
  stubHost(on)
  await $.command.run({ command: 'fleet', args: '' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: 'Fleet: 2/3 ok' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /gateway {2}gateway detail/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /claude {2}FLEET/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /codex {2}NOT-FLEET/ })).toBeDefined()
    await ui.unmount()
  }
})

test('without a surface the command answers in text', async ($, on) => {
  stubHost(on, { surfaces: [] })
  const out = await $.command.run({ command: 'fleet', args: '' })
  expect(out.text).toContain('Fleet: 2/3 ok')
  expect(out.text).toContain('warn tailscale')
})

test('the data root goes to doctor as --root', { options: { dataRoot: '/ops' } }, async ($, on) => {
  const host = stubHost(on)
  await $.command.run({ command: 'fleet', args: '' })
  const doctor = host.runs.find((argv) => argv.some((a) => a.endsWith('doctor.py')))
  expect(doctor.slice(-2)).toEqual(['--root', '/ops'])
})

test('a critical check turning red toasts once, a warning does not', async ($, on) => {
  const host = stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await host.clock.settle()
  expect(host.toasts).toEqual([])
  host.state.checks = [check('wing', false), check('gateway', false, true), check('tailscale', false)]
  await host.clock.advance(120_000)
  expect(host.toasts).toEqual(['Fleet critical check red: gateway (/fleet)'])
  await host.clock.advance(120_000)
  expect(host.toasts.length).toBe(1)
})

test('a doctor that prints garbage shows the failure', async ($, on) => {
  stubHost(on, { surfaces: [], broken: true })
  const out = await $.command.run({ command: 'fleet', args: '' })
  expect(out.text).toBe('Fleet doctor failed: trace')
})
