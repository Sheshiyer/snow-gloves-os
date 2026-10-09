import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {createFleetBoard, displayValue, FleetClient, FLEET_STATES, graphLines, orderTasks, validateTask} from './fleet-tasks';

const task = {id: 'task-1', status: 'running', title: '<img src=x onerror=alert(1)>', project: 'snowgloves', category: 'development', node_id: 'mac-coding-1', runtime: 'codex'};
const signal = () => new AbortController().signal;
const json = (data: unknown) => new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}});

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
  it('supports detail wrappers and encoded IDs, and validates events', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json({task})).mockResolvedValueOnce(json({events: [{message: '<script>unsafe</script>', artifact: {path: '/artifact.json', sha256: 'abc'}}]}));
    const client = new FleetClient('key', fetcher);
    expect(await client.detail('a/b', signal())).toEqual(task);
    expect(fetcher.mock.calls[0][0]).toBe('/api/fleet/tasks/a%2Fb');
    expect(await client.events('task-1', signal())).toHaveLength(1);
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
    expect(text).toContain('Task graph · verified');
    expect(text).toContain('<i>sentinel</i> · verify · succeeded · artifact attached');
    expect(el.find('button', 'Cancel task and open children').disabled).toBe(true);
    board.pause(true);
  });
});
