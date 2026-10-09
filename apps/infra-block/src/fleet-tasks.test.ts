import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {createFleetBoard, displayValue, fanoutAction, FleetClient, FLEET_STATES, graphLines, orderTasks, validateFanoutPlan, validateTask} from './fleet-tasks';

const task = {id: 'task-1', status: 'running', title: '<img src=x onerror=alert(1)>', project: 'snowgloves', category: 'development', node_id: 'mac-coding-1', runtime: 'codex'};
const signal = () => new AbortController().signal;
const json = (data: unknown) => new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}});
const rootId = 'a'.repeat(32);
const fanoutPlan = (root = rootId) => ({
  plan_id: 'b'.repeat(32), root_id: root, children: [
    {id: 'c'.repeat(32), parent_id: root, logical_role: 'librarian', stage: 'reference', access: 'read', order: 1},
    {id: 'd'.repeat(32), parent_id: root, logical_role: 'sentinel', stage: 'verify', access: 'read', order: 2},
  ],
});

// Small DOM harness: rejects all HTML insertion; tests exercise real controller handlers.
class ElementHarness {
  children: ElementHarness[] = [];
  attrs: Record<string, string> = {};
  textContent = '';
  className = '';
  value = '';
  disabled = false;
  type = '';
  onclick?: () => void | Promise<void>;
  onsubmit?: (event: {preventDefault(): void}) => void | Promise<void>;
  oninput?: () => void;
  constructor(public tagName: string) {}
  set innerHTML(_: string) { throw new Error('Unsafe HTML insertion'); }
  append(...nodes: ElementHarness[]) { this.children.push(...nodes); }
  replaceChildren(...nodes: ElementHarness[]) { this.children = [...nodes]; }
  setAttribute(key: string, value: string) { this.attrs[key] = value; }
  all(): ElementHarness[] { return [this, ...this.children.flatMap(child => child.all())]; }
  find(tag: string, text?: string): ElementHarness { const result = this.all().find(child => child.tagName === tag && (text === undefined || child.textContent === text)); if (!result) throw new Error(`Missing ${tag} ${text}`); return result; }
}
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const submitEvent = {preventDefault() {}};

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('Fleet client contract', () => {
  it('calls browser fetch without binding the client as its receiver', async () => {
    let receiver: unknown;
    vi.stubGlobal('fetch', function(this: unknown) {
      receiver = this;
      if (this instanceof FleetClient) throw new TypeError('Illegal invocation');
      return Promise.resolve(json({tasks: [task]}));
    });
    expect(await new FleetClient('key').tasks(signal())).toEqual([task]);
    expect(receiver).not.toBeInstanceOf(FleetClient);
  });
  it('uses same-origin proxy and a bearer header without persistent credentials', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({tasks: [task]}));
    const storage = {setItem: vi.fn()}; vi.stubGlobal('localStorage', storage); vi.stubGlobal('sessionStorage', storage);
    const client = new FleetClient('operator-secret', fetcher);
    expect(await client.tasks(signal())).toEqual([task]);
    expect(fetcher.mock.calls[0][0]).toBe('/api/fleet/tasks');
    expect(fetcher.mock.calls[0][1]).toMatchObject({method: 'GET', credentials: 'omit', cache: 'no-store', headers: {Authorization: 'Bearer operator-secret'}});
    expect(JSON.stringify(client)).not.toContain('operator-secret'); expect(storage.setItem).not.toHaveBeenCalled();
  });
  it('sends the stable submission key and fixed project/runtime contract', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({task})); const client = new FleetClient('key', fetcher);
    const body = {project: 'snowgloves', runtime: 'codex', category: 'development', brief: 'Inspect', title: 'Inspect', idempotency_key: 'stable'};
    await client.request('/tasks', signal(), body);
    expect(fetcher.mock.calls[0][1]).toMatchObject({method: 'POST', body: JSON.stringify(body)});
  });
  it('posts exactly an empty object to the bounded fanout route and fails closed on invalid results', async () => {
    const fetcher = vi.fn().mockResolvedValue(json(fanoutPlan()));
    const client = new FleetClient('key', fetcher);
    expect(await client.fanout(rootId, signal())).toEqual(fanoutPlan());
    expect(fetcher.mock.calls[0][0]).toBe(`/api/fleet/tasks/${rootId}/fanout`);
    expect(fetcher.mock.calls[0][1]).toMatchObject({method: 'POST', body: '{}', credentials: 'omit'});
    await expect(client.fanout('not-a-task-id', signal())).rejects.toThrow('32-character');
    expect(fetcher).toHaveBeenCalledTimes(1);
    fetcher.mockResolvedValueOnce(json({...fanoutPlan(), root_id: 'e'.repeat(32)}));
    await expect(client.fanout(rootId, signal())).rejects.toThrow('Invalid fanout plan response');
    await expect(client.request(`/tasks/${rootId}/fanout`, signal(), {scope: 'all'})).rejects.toThrow('Fanout accepts no options');
    await expect(client.request(`/tasks/${rootId}/events`, signal(), {})).rejects.toThrow('Unsupported');
  });
  it('supports detail wrappers and encoded IDs, and validates events', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({task})).mockResolvedValueOnce(json({events: [{message: '<script>unsafe</script>', artifact: {path: '/artifact.json', sha256: 'abc'}}]}));
    const client = new FleetClient('key', fetcher);
    expect(await client.detail('a/b', signal())).toEqual(task);
    expect(fetcher.mock.calls[0][0]).toBe('/api/fleet/tasks/a%2Fb');
    expect(await client.events('task-1', signal())).toHaveLength(1);
  });
  it.each(['/tasks', `/tasks/${rootId}/fanout`])('allows the 90-second bridge window but bounds planning at %s', async path => {
    let resolve: ((response: Response) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    const fetcher = vi.fn((_path, init) => new Promise<Response>((accept, reject) => {
      resolve = accept; requestSignal = init?.signal as AbortSignal;
      requestSignal.addEventListener('abort', () => reject(new Error('aborted')), {once: true});
    }));
    const client = new FleetClient('key', fetcher);
    const pending = client.request(path, signal(), {});
    await vi.advanceTimersByTimeAsync(90_500);
    expect(requestSignal?.aborted).toBe(false);
    resolve!(json(fanoutPlan()));
    await expect(pending).resolves.toEqual(fanoutPlan());
    const bounded = client.request(path, signal(), {});
    const failure = expect(bounded).rejects.toThrow('Coordinator request timed out');
    await vi.advanceTimersByTimeAsync(100_001);
    await failure;
    expect(requestSignal?.aborted).toBe(true);
  });
  it('rejects duplicate children and plans without a final Sentinel before claiming success', () => {
    const duplicate = fanoutPlan(); duplicate.children[1].id = duplicate.children[0].id;
    const duplicateRole = fanoutPlan(); duplicateRole.children[1].logical_role = 'librarian';
    const wrongFinal = fanoutPlan(); wrongFinal.children[1].stage = 'review';
    for (const plan of [duplicate, duplicateRole, wrongFinal]) {
      expect(() => validateFanoutPlan(plan, rootId)).toThrow('Invalid fanout plan response');
    }
  });
  it('rejects malformed task data and arbitrary routes before fetch', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({tasks: [{...task, status: 'invented'}]})); const client = new FleetClient('key', fetcher);
    await expect(client.tasks(signal())).rejects.toThrow('Invalid coordinator task');
    await expect(client.request('/admin', signal())).rejects.toThrow('Unsupported'); expect(fetcher).toHaveBeenCalledTimes(1);
    expect(() => new FleetClient('')).toThrow('valid operator token'); expect(() => new FleetClient('key\nheader')).toThrow();
    for (const status of FLEET_STATES) expect(validateTask({...task, status}).status).toBe(status);
  });
  it('does not expose error bodies or credential-like upstream errors', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('Bearer SECRET upstream stack', {status: 403}));
    await expect(new FleetClient('key', fetcher).tasks(signal())).rejects.toThrow('Access denied');
    fetcher.mockResolvedValue(new Response('not-json', {status: 200}));
    await expect(new FleetClient('key', fetcher).tasks(signal())).rejects.toThrow('invalid JSON');
  });
  it('rejects invalid event envelopes', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({events: ['unstructured']}));
    await expect(new FleetClient('key', fetcher).events('task-1', signal())).rejects.toThrow('Invalid coordinator event list');
    expect(displayValue({message: '<script>alert(1)</script>'})).toContain('<script>');
  });
  it('treats the optional server action as display data only', () => {
    const root = validateTask({...task, id: rootId, parent_id: null});
    expect(fanoutAction(root)).toBeNull(); // Older coordinators remain usable.
    expect(fanoutAction({...root, fanout_action: {available: true, planned: false, reason: 'Plan roles.'}})).toEqual({
      available: true, planned: false, reason: 'Plan roles.',
    });
    expect(fanoutAction({...root, fanout_action: {available: true, planned: true, reason: 'Contradiction'}})).toBeNull();
    expect(() => validateFanoutPlan({root_id: rootId, plan_id: 'bad', children: []}, rootId)).toThrow('Invalid fanout plan');
  });
});

describe('Hermes board lifecycle', () => {
  function mount() {
    vi.stubGlobal('document', {createElement: (tag: string) => new ElementHarness(tag)});
    const fetcher = vi.fn(async (path: string) => path.endsWith('/events') ? json({events: [{message: '<script>alert(1)</script>', artifact: {path: '/artifact', sha256: 'abc'}}]}) : path === '/api/fleet/tasks' ? json({tasks: [task]}) : json({task}));
    vi.stubGlobal('fetch', fetcher);
    const board = createFleetBoard(); const el = board.element as unknown as ElementHarness;
    return {board, el, fetcher};
  }
  async function connect(el: ElementHarness) { el.find('input').value = 'secret-token'; await el.find('form').onsubmit?.(submitEvent); await flush(); }
  it('requires explicit connection and inserts hostile output as text, never HTML', async () => {
    const {board, el, fetcher} = mount(); board.activate(); expect(fetcher).not.toHaveBeenCalled();
    expect(el.find('button', 'Submit to Coding 01').disabled).toBe(true);
    await connect(el); expect(el.find('input').value).toBe('');
    const taskButton = el.all().find(child => child.className.includes('fleet-task') && child.tagName === 'button')!;
    expect(taskButton.textContent).toContain('<img src=x'); await taskButton.onclick?.(); await flush();
    expect(el.find('pre').textContent).toContain('<script>alert(1)</script>');
    expect(el.find('pre').textContent).toContain('sha256');
    board.pause(true);
  });
  it('stops polling and aborts outstanding requests on close, then requires fresh credentials', async () => {
    const {board, el, fetcher} = mount(); board.activate(); await connect(el);
    const count = fetcher.mock.calls.length; board.pause(true); await vi.advanceTimersByTimeAsync(12000);
    expect(fetcher).toHaveBeenCalledTimes(count); expect(el.find('button', 'Submit to Coding 01').disabled).toBe(true);
    board.activate(); await flush(); expect(fetcher).toHaveBeenCalledTimes(count);
    const pending = vi.fn((_path: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => { init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))); }));
    vi.stubGlobal('fetch', pending); await connect(el); board.pause(true); await flush();
    expect(pending.mock.calls[0][1].signal?.aborted).toBe(true);
    expect(el.all().some(child => child.textContent.includes('Disconnected:'))).toBe(false);
  });
  it('clears stale task records after a connection failure', async () => {
    const {board, el, fetcher} = mount(); board.activate(); await connect(el);
    expect(el.all().some(child => child.textContent.includes(task.title))).toBe(true);
    fetcher.mockRejectedValue(new Error('Network unavailable')); await vi.advanceTimersByTimeAsync(4000); await flush();
    expect(el.all().some(child => child.textContent.includes(task.title))).toBe(false);
    expect(el.all().some(child => child.textContent.includes('No current task data'))).toBe(true);
    expect(el.find('button', 'Submit to Coding 01').disabled).toBe(true); board.pause(true);
  });
});

describe('read-only role planning board control', () => {
  const root = {
    id: rootId, status: 'succeeded', title: 'Root development task', created: 1,
    parent_id: null, project: 'snowgloves', category: 'development', runtime: 'codex',
  };
  const childRows = [
    {id: 'c'.repeat(32), status: 'queued', title: 'References', created: 2, parent_id: rootId, logical_role: 'librarian', stage: 'reference'},
    {id: 'd'.repeat(32), status: 'queued', title: 'Verify', created: 3, parent_id: rootId, logical_role: 'sentinel', stage: 'verify'},
  ];
  const action = (available = true, planned = false, reason = 'Read-only roles can be planned for this task.') => ({
    available, planned, reason,
  });

  async function connectAndSelect(el: ElementHarness) {
    el.find('input').value = 'operator-token';
    await el.find('form').onsubmit?.(submitEvent);
    await flush();
    const rootButton = el.all().find(child => child.tagName === 'button' && child.className.includes('fleet-task') && child.textContent.includes('Root development task'));
    if (!rootButton) throw new Error('Missing root task button.');
    await rootButton.onclick?.();
    await flush();
  }

  function mount(actionValue: unknown = action(), pendingFanout = false, twoRoots = false) {
    vi.stubGlobal('document', {createElement: (tag: string) => new ElementHarness(tag)});
    let planned = false;
    let resolveFanout: ((value: Response) => void) | undefined;
    let fanoutSignal: AbortSignal | undefined;
    const second = {...root, id: 'e'.repeat(32), title: 'Second root', created: 4};
    const detail = (id: string) => {
      const current = id === second.id ? second : root;
      const isPlanned = current.id === rootId && planned;
      return {
        ...current,
        fanout_action: isPlanned ? action(false, true, 'Read-only roles are already planned for this task.') : actionValue,
        graph: isPlanned ? {
          status: 'incomplete',
          children: [
            {logical_role: 'librarian', stage: 'reference', status: 'queued', artifact: null, hold_reason: '<script>planner-content</script> is untrusted'},
            {logical_role: 'sentinel', stage: 'verify', status: 'queued', artifact: null, hold_reason: 'Waiting: planned predecessor must succeed'},
          ],
        } : {status: 'none', children: []},
      };
    };
    const fetcher = vi.fn((path: string, init?: RequestInit) => {
      if (path === `/api/fleet/tasks/${rootId}/fanout`) {
        planned = true;
        fanoutSignal = init?.signal ?? undefined;
        if (pendingFanout) return new Promise<Response>(resolve => { resolveFanout = resolve; });
        return Promise.resolve(json(fanoutPlan()));
      }
      if (path.endsWith('/events')) return Promise.resolve(json({events: []}));
      if (path === '/api/fleet/tasks') return Promise.resolve(json({tasks: planned ? [root, ...childRows, ...(twoRoots ? [second] : [])] : [root, ...(twoRoots ? [second] : [])]}));
      const id = path.split('/').at(-1) || rootId;
      return Promise.resolve(json({task: detail(id)}));
    });
    vi.stubGlobal('fetch', fetcher);
    const board = createFleetBoard();
    return {
      board, el: board.element as unknown as ElementHarness, fetcher,
      resolveFanout: () => resolveFanout?.(json(fanoutPlan())),
      fanoutSignal: () => fanoutSignal,
    };
  }

  it('posts exactly once only after an admitted click, then refreshes the selected graph without duplicate children', async () => {
    const {board, el, fetcher, resolveFanout} = mount(action(), true);
    board.activate(); await connectAndSelect(el);
    const button = el.find('button', 'Plan read-only roles');
    expect(button.type).toBe('button');
    expect(button.disabled).toBe(false);
    const first = button.onclick?.();
    const second = button.onclick?.();
    expect(fetcher.mock.calls.filter(call => call[0] === `/api/fleet/tasks/${rootId}/fanout`)).toHaveLength(1);
    expect(fetcher.mock.calls.find(call => call[0] === `/api/fleet/tasks/${rootId}/fanout`)?.[1]).toMatchObject({method: 'POST', body: '{}'});
    resolveFanout();
    await first; await second; await flush();
    expect(el.all().filter(child => child.textContent.includes('Read-only roles are already planned'))).toHaveLength(1);
    expect(el.find('button', 'Plan read-only roles').disabled).toBe(true);
    const graph = el.all().filter(child => child.className === 'fleet-graph');
    expect(graph).toHaveLength(1);
    expect(graph[0]!.all().filter(child => child.textContent.includes('librarian · reference'))).toHaveLength(1);
    expect(el.all().some(child => child.textContent.includes('hold: Waiting: planned predecessor must succeed'))).toBe(true);
    expect(el.all().some(child => child.textContent.includes('<script>planner-content</script> is untrusted'))).toBe(true);
    board.pause(true);
  });

  it('keeps the control disabled for default-off/observer contracts and omits it for old or malformed contracts', async () => {
    const denied = mount(action(false, false, 'Read-only role planning is not permitted for this account.'));
    denied.board.activate(); await connectAndSelect(denied.el);
    const disabled = denied.el.find('button', 'Plan read-only roles');
    expect(disabled.disabled).toBe(true);
    await disabled.onclick?.();
    expect(denied.fetcher.mock.calls.some(call => String(call[0]).endsWith('/fanout'))).toBe(false);
    denied.board.pause(true);

    const old = mount(null);
    old.board.activate(); await connectAndSelect(old.el);
    expect(old.el.all().some(child => child.textContent === 'Plan read-only roles')).toBe(false);
    expect(old.el.all().some(child => child.textContent.includes('Root development task'))).toBe(true);
    old.board.pause(true);

    const malformed = mount({available: true, planned: false, reason: 7});
    malformed.board.activate(); await connectAndSelect(malformed.el);
    expect(malformed.el.all().some(child => child.textContent === 'Plan read-only roles')).toBe(false);
    malformed.board.pause(true);
  });

  it('fails closed on a malformed successful plan response', async () => {
    const {board, el, fetcher} = mount();
    fetcher.mockImplementation((path: string) => {
      if (path === `/api/fleet/tasks/${rootId}/fanout`) return Promise.resolve(json({plan_id: 'bad'}));
      if (path.endsWith('/events')) return Promise.resolve(json({events: []}));
      if (path === '/api/fleet/tasks') return Promise.resolve(json({tasks: [root]}));
      return Promise.resolve(json({task: {...root, fanout_action: action(), graph: {status: 'none', children: []}}}));
    });
    board.activate(); await connectAndSelect(el);
    await el.find('button', 'Plan read-only roles').onclick?.();
    await flush();
    expect(el.all().some(child => child.textContent.includes('Disconnected: Invalid fanout plan response.'))).toBe(true);
    expect(el.find('button', 'Submit to Coding 01').disabled).toBe(true);
  });

  it('aborts a pending plan on selection or pause and never posts from a stale/disconnected control', async () => {
    const selected = mount(action(), true, true);
    selected.board.activate(); await connectAndSelect(selected.el);
    const control = selected.el.find('button', 'Plan read-only roles');
    void control.onclick?.();
    await flush();
    const next = selected.el.all().find(child => child.tagName === 'button' && child.className.includes('fleet-task') && child.textContent.includes('Second root'));
    if (!next) throw new Error('Missing second root task button.');
    await next.onclick?.(); await flush();
    expect(selected.fanoutSignal()?.aborted).toBe(true);
    selected.resolveFanout(); await flush();
    expect(selected.el.all().some(child => child.textContent.includes('Read-only role plan accepted.'))).toBe(false);
    selected.board.pause(true);

    const paused = mount(action(), true);
    paused.board.activate(); await connectAndSelect(paused.el);
    const stale = paused.el.find('button', 'Plan read-only roles');
    void stale.onclick?.(); await flush();
    paused.board.pause(true);
    expect(paused.fanoutSignal()?.aborted).toBe(true);
    const posts = paused.fetcher.mock.calls.filter(call => String(call[0]).endsWith('/fanout')).length;
    await stale.onclick?.();
    expect(paused.fetcher.mock.calls.filter(call => String(call[0]).endsWith('/fanout'))).toHaveLength(posts);
    paused.resolveFanout(); await flush();

    const disconnected = mount(action());
    disconnected.board.activate(); await connectAndSelect(disconnected.el);
    const afterDisconnect = disconnected.el.find('button', 'Plan read-only roles');
    await disconnected.el.find('button', 'Disconnect').onclick?.();
    await afterDisconnect.onclick?.();
    expect(disconnected.fetcher.mock.calls.some(call => String(call[0]).endsWith('/fanout'))).toBe(false);
  });
});

describe('Task graph rendering', () => {
  const parent = {id: 'p', status: 'succeeded', title: 'Root', created: 1, logical_role: 'cto', parent_id: null};
  const kidB = {id: 'b', status: 'queued', title: 'Second', created: 3, logical_role: 'sentinel', stage: 'verify', parent_id: 'p'};
  const kidA = {id: 'a', status: 'succeeded', title: 'First', created: 2, logical_role: 'librarian', stage: 'reference', parent_id: 'p'};
  const other = {id: 'o', status: 'queued', title: 'Other root', created: 4, parent_id: null};
  it('places children under their parent, oldest first, and keeps orphans as roots', () => {
    const orphan = {...kidA, id: 'x', parent_id: 'missing'};
    const order = orderTasks([other, kidB, parent, kidA, orphan] as never);
    expect(order.map(row => [row.task.id, row.child])).toEqual([['o', false], ['p', false], ['a', true], ['b', true], ['x', false]]);
  });
  it('summarises the coordinator graph and stays silent without children', () => {
    expect(graphLines(parent as never)).toEqual([]);
    expect(graphLines({...parent, graph: {children: [], status: 'none'}} as never)).toEqual([]);
    expect(graphLines({...parent, graph: {status: 'incomplete', children: [{logical_role: 'librarian', stage: 'reference', status: 'succeeded', artifact: {path: 'a', sha256: 'x'}}, {logical_role: 'sentinel', stage: null, status: 'queued', artifact: null}]}} as never))
      .toEqual(['Task graph · incomplete', 'librarian · reference · succeeded · artifact attached', 'sentinel · — · queued · no artifact']);
    expect(graphLines({...parent, graph: {status: 'incomplete', children: [{logical_role: 'sentinel', stage: 'verify', status: 'failed', artifact: null, superseded_by: 'n'}]}} as never)[1]).toBe('sentinel · verify · failed · no artifact · retried');
    expect(graphLines({...parent, graph: {status: 'incomplete', children: [{logical_role: 'sentinel', stage: 'verify', status: 'queued', artifact: null, hold_reason: 'Waiting: source prerequisite'}]}} as never)[1])
      .toBe('sentinel · verify · queued · no artifact · hold: Waiting: source prerequisite');
  });
  it('shows role and stage on labels and renders the graph panel as text', async () => {
    vi.stubGlobal('document', {createElement: (tag: string) => new ElementHarness(tag)});
    const detail = {...parent, title: '<b>Root</b>', graph: {status: 'verified', children: [{logical_role: '<i>sentinel</i>', stage: 'verify', status: 'succeeded', artifact: {path: 'p', sha256: 's'}}]}};
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path.endsWith('/events') ? json({events: []}) : path === '/api/fleet/tasks' ? json({tasks: [parent, kidA]}) : json({task: detail})));
    const board = createFleetBoard(); const el = board.element as unknown as ElementHarness; board.activate();
    el.find('input').value = 'secret-token'; await el.find('form').onsubmit?.(submitEvent); await flush();
    const buttons = el.all().filter(child => child.tagName === 'button' && child.className.includes('fleet-task'));
    expect(buttons.map(button => button.className.includes('fleet-task-child'))).toEqual([false, true]);
    expect(buttons[1].textContent).toContain('librarian · reference');
    await buttons[0].onclick?.(); await flush();
    const text = el.all().map(child => child.textContent);
    expect(text).toContain('Task graph · artifact checks passed · content review pending');
    expect(text).toContain('<i>sentinel</i> · verify · succeeded · artifact attached');
    expect(el.find('button', 'Cancel task and open children').disabled).toBe(true);
    board.pause(true);
  });
  it('cancels open children after the root succeeded and cannot reuse the control after pause', async () => {
    vi.stubGlobal('document', {createElement: (tag: string) => new ElementHarness(tag)});
    let cancelled = false;
    const fetcher = vi.fn(async (path: string) => {
      if (path.endsWith('/cancel')) cancelled = true;
      const detail = {...parent, graph: {status: cancelled ? 'cancelled' : 'incomplete', children: [{...kidB, status: cancelled ? 'cancelled' : 'queued'}]}};
      return path.endsWith('/events') ? json({events: []}) : path === '/api/fleet/tasks' ? json({tasks: [parent]}) : json({task: detail});
    });
    vi.stubGlobal('fetch', fetcher);
    const board = createFleetBoard(); const el = board.element as unknown as ElementHarness; board.activate();
    el.find('input').value = 'synthetic-token'; await el.find('form').onsubmit?.(submitEvent); await flush();
    await el.all().find(child => child.tagName === 'button' && child.className.includes('fleet-task'))!.onclick?.(); await flush();
    const cancel = el.find('button', 'Cancel task and open children');
    expect(cancel.disabled).toBe(false);
    await cancel.onclick?.(); await flush();
    expect(fetcher.mock.calls.filter(call => call[0].endsWith('/cancel'))).toHaveLength(1);
    expect(el.find('button', 'Cancel task and open children').disabled).toBe(true);
    board.pause(true); await cancel.onclick?.();
    expect(fetcher.mock.calls.filter(call => call[0].endsWith('/cancel'))).toHaveLength(1);
  });
});
