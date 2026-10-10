import { expect, test } from 'claude-code/testing'

const agent = (slug: string, over = {}) => ({
  slug, role: slug.toUpperCase() + ' role', layer: 'L', description: 'does ' + slug, prompt: 'You are ' + slug,
  tools: ['Read', 'Grep', 'Glob'], readonly: true, default_skills: ['snowgloves:x'], hooks: [{ id: 'h1', globs: ['*a*'] }],
  escalates_to: 'cto', enabled: true, ...over,
})

const PANE = {
  plugin: 'sg-org', component: 'Pane', requestId: 'sg-org', viewport: { columns: 140, rows: 40 },
  props: { title: 'Org', isFocused: true, bodyColumns: 100, placement: 'inline', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

function stubHost(on, { restricted = false, baseUrl = '', surfaces = ['terminal'], broken = false } = {}) {
  const registered: { name: string; description: string; prompt: string; tools: string[] }[] = []
  const runs: string[][] = []
  const table = {
    schema: 'snowgloves.mods-agents.v1', tenant: 'acme', restricted,
    agents: [agent('ceo'), agent('sentinel', { enabled: !restricted ? true : false }), agent('cto', { readonly: false, tools: ['Read', 'Bash'] })],
  }
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('env.get', ($, e) => ({ value: { SNOWGLOVES_TENANT: 'acme', ANTHROPIC_BASE_URL: baseUrl || undefined }[e.name] }))
  on('fs.exists', () => ({ value: false }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.log', () => ({ value: undefined }))
  on('agent.register', ($, e) => {
    registered.push({ name: e.name, description: e.description, prompt: e.prompt, tools: [...(e.tools || [])] })
    return { value: undefined }
  })
  on('process.run', ($, e) => {
    runs.push([...e.argv])
    if (broken) return { value: { exitCode: 2, stdout: '{"error":"unknown tenant"}', stderr: '' } }
    return { value: { exitCode: 0, stdout: JSON.stringify(table), stderr: '' } }
  })
  on('agent.offer', () => ({ isOffered: true }))
  on('agent.spawn', ($, e) => ({ model: e.model || 'inherited', agentId: 'a1' }))
  return { registered, runs }
}

const OFFER = (agent: string, plugin = 'sg-org') => ({ agent, description: 'd', source: 'plugin', provider: { plugin, tier: 'user' } }) as const
const SPAWN = (subagentType: string) => ({
  tool_use_id: 'tu1', prompt: 'go', description: 'd', subagentType, provider: { plugin: 'sg-org', tier: 'user' }, parentModel: 'claude-x',
}) as const

test('each agent is registered as a subagent type from the bridge table', async ($, on) => {
  const host = stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(host.registered.map((a) => a.name)).toEqual(['ceo', 'sentinel', 'cto'])
  expect(host.registered[0]).toEqual({ name: 'ceo', description: 'CEO role. does ceo', prompt: 'You are ceo', tools: ['Read', 'Grep', 'Glob'] })
  expect(host.runs[0].slice(-3)).toEqual(['agents', '--tenant', 'acme'])
})

test('/org draws a lane per agent on both surfaces', async ($, on) => {
  stubHost(on)
  await $.command.run({ command: 'org', args: '' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: 'Org for acme' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'cto  CTO role' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /tools: Read, Bash .*escalates to: cto.*heartbeat: stale/ })).toBeDefined()
    await ui.unmount()
  }
})

test('without a surface /org answers in text', async ($, on) => {
  stubHost(on, { surfaces: [] })
  const out = await $.command.run({ command: 'org', args: '' })
  expect(out.text.split('\n')[0]).toBe('Org for acme')
})

test('a role the restricted tenant has not enabled is withheld, others and foreign agents are not', async ($, on) => {
  stubHost(on, { restricted: true })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect((await $.agent.offer(OFFER('sg-org:sentinel'))).isOffered).toBe(false)
  expect((await $.agent.offer(OFFER('sg-org:ceo'))).isOffered).toBe(true)
  expect((await $.agent.offer(OFFER('Explore', 'engine'))).isOffered).toBe(true)
})

test('an unrestricted tenant is offered every role', async ($, on) => {
  stubHost(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect((await $.agent.offer(OFFER('sg-org:sentinel'))).isOffered).toBe(true)
})

test('the role combo applies only behind OmniRoute', { options: { roleCombos: 'sentinel=noesis-verify' } }, async ($, on) => {
  stubHost(on, { baseUrl: 'http://127.0.0.1:20128' })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect((await $.agent.spawn(SPAWN('sg-org:sentinel'))).model).toBe('noesis-verify')
  expect((await $.agent.spawn(SPAWN('sg-org:ceo'))).model).toBe('inherited')
  expect((await $.agent.spawn(SPAWN('Explore'))).model).toBe('inherited')
})

test('off OmniRoute the model is left alone', { options: { roleCombos: 'sentinel=noesis-verify' } }, async ($, on) => {
  stubHost(on, { baseUrl: 'https://api.anthropic.com' })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect((await $.agent.spawn(SPAWN('sg-org:sentinel'))).model).toBe('inherited')
})

test('a bridge that fails leaves no agents and /org says why', async ($, on) => {
  stubHost(on, { surfaces: [], broken: true })
  const out = await $.command.run({ command: 'org', args: '' })
  expect(out.text).toContain('Org unavailable')
})
