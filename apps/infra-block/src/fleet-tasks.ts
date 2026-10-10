import './fleet-tasks.css';

type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue => typeof value === 'object' && value !== null && !Array.isArray(value);
export const FLEET_STATES = ['queued', 'running', 'cancel_requested', 'cancelled', 'succeeded', 'failed', 'interrupted', 'needs_input'] as const;
export type FleetTask = RecordValue & {id: string; status: typeof FLEET_STATES[number]};
export interface FanoutAction {available: boolean; planned: boolean; reason: string}
export interface FanoutPlan {plan_id: string; root_id: string; children: RecordValue[]}
const TASK_ID = /^[a-f0-9]{32}$/;
const FANOUT_ROLES = ['ceo', 'cto', 'chief-of-staff', 'librarian', 'interpreter', 'dispatcher', 'sentinel'];
const FANOUT_STAGES = ['plan', 'reference', 'review', 'dispatch', 'verify'];
const MAX_FLEET_BODY_BYTES = 32 * 1024;
const FLEET_REQUEST_TIMEOUT_MS = 10_000;
const FLEET_PLANNING_TIMEOUT_MS = 100_000; // The Hermes bridge can run for 90 seconds.

export function validateTask(value: unknown): FleetTask {
  if (!record(value) || typeof value.id !== 'string' || !value.id || !FLEET_STATES.includes(value.status as typeof FLEET_STATES[number])) throw new Error('Invalid coordinator task response.');
  return value as FleetTask;
}
/** A missing or malformed optional display contract has no authority and no UI action. */
export function fanoutAction(task: FleetTask): FanoutAction | null {
  const action = task.fanout_action;
  if (!record(action) || typeof action.available !== 'boolean' || typeof action.planned !== 'boolean'
      || typeof action.reason !== 'string' || !action.reason.trim() || action.reason.length > 280
      || (action.available && action.planned)) return null;
  return {available: action.available, planned: action.planned, reason: action.reason};
}
export function validateFanoutPlan(value: unknown, rootId: string): FanoutPlan {
  if (!record(value) || !TASK_ID.test(rootId) || value.root_id !== rootId
      || typeof value.plan_id !== 'string' || !TASK_ID.test(value.plan_id)
      || !Array.isArray(value.children) || value.children.length < 2 || value.children.length > 7
      || !value.children.every((child, index) => record(child)
        && typeof child.id === 'string' && TASK_ID.test(child.id)
        && child.parent_id === rootId && child.access === 'read'
        && typeof child.logical_role === 'string' && FANOUT_ROLES.includes(child.logical_role)
        && typeof child.stage === 'string' && FANOUT_STAGES.includes(child.stage)
        && child.order === index + 1)
      || new Set(value.children.map(child => child.id)).size !== value.children.length
      || new Set(value.children.map(child => child.logical_role)).size !== value.children.length
      || value.children.at(-1)?.logical_role !== 'sentinel' || value.children.at(-1)?.stage !== 'verify') {
    throw new Error('Invalid fanout plan response.');
  }
  return value as unknown as FanoutPlan;
}
export function displayValue(value: unknown): string {
  if (value === undefined || value === null) return '—';
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
/** Roots in server order, each followed by its children (oldest first). Children never nest further. */
export function orderTasks(tasks: FleetTask[]): {task: FleetTask; child: boolean}[] {
  const ids = new Set(tasks.map(item => item.id));
  const kids = new Map<string, FleetTask[]>();
  const roots: FleetTask[] = [];
  for (const item of tasks) {
    const parent = item.parent_id;
    if (typeof parent === 'string' && ids.has(parent)) kids.set(parent, [...(kids.get(parent) ?? []), item]);
    else roots.push(item);
  }
  return roots.flatMap(root => [{task: root, child: false}, ...(kids.get(root.id) ?? []).sort((a, b) => Number(a.created) - Number(b.created)).map(item => ({task: item, child: true}))]);
}
/** Text rows for a parent's coordinator-derived graph; empty when the task has no children. */
export function graphLines(task: FleetTask): string[] {
  const graph = task.graph;
  if (!record(graph) || !Array.isArray(graph.children) || !graph.children.length) return [];
  const status = graph.status === 'verified'
    ? 'artifact checks passed · content review pending'
    : displayValue(graph.status);
  return [`Task graph · ${status}`, ...graph.children.filter(record).map(kid => {
    const hold = typeof kid.hold_reason === 'string' && kid.hold_reason.trim() && kid.hold_reason.length <= 280
      ? ` · hold: ${kid.hold_reason}` : '';
    return [kid.logical_role, kid.stage, kid.status, kid.artifact ? 'artifact attached' : 'no artifact']
      .map(displayValue).join(' · ') + (kid.superseded_by ? ' · retried' : '') + hold;
  })];
}
export class FleetClient {
  #token: string;
  constructor(token: string, private transport: typeof fetch = (input, init) => fetch(input, init)) {
    if (!token.trim() || /[\r\n]/.test(token)) throw new Error('Enter a valid operator token.');
    this.#token = token.trim();
  }
  async request(path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
    const method = body === undefined ? 'GET' : 'POST';
    const getAllowed = path === '/tasks' || /^\/tasks\/[^/?#]+(?:\/events)?$/.test(path);
    const postAllowed = path === '/tasks' || /^\/tasks\/[^/?#]+\/(?:cancel|fanout)$/.test(path);
    if ((method === 'GET' && !getAllowed) || (method === 'POST' && !postAllowed)) throw new Error('Unsupported fleet operation.');
    if (path.endsWith('/fanout') && (!record(body) || Object.keys(body).length)) throw new Error('Fanout accepts no options.');
    const encoded = body === undefined ? undefined : JSON.stringify(body);
    if (encoded !== undefined && new TextEncoder().encode(encoded).byteLength > MAX_FLEET_BODY_BYTES) throw new Error('Fleet request body is too large.');
    const bounded = new AbortController();
    let timedOut = false;
    const abort = () => bounded.abort();
    signal.addEventListener('abort', abort, {once: true});
    if (signal.aborted) bounded.abort();
    const planning = method === 'POST' && (path === '/tasks' || path.endsWith('/fanout'));
    const timeout = setTimeout(() => { timedOut = true; bounded.abort(); }, planning ? FLEET_PLANNING_TIMEOUT_MS : FLEET_REQUEST_TIMEOUT_MS);
    try {
      const response = await this.transport(`/api/fleet${path}`, {
      method, signal: bounded.signal, cache: 'no-store', credentials: 'omit',
      headers: {Authorization: `Bearer ${this.#token}`, 'Content-Type': 'application/json'},
      ...(encoded === undefined ? {} : {body: encoded}),
      });
      // Never display upstream error bodies; keep the timeout through body parsing.
      if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? 'Access denied. Check your operator token and project permission.' : `Coordinator request failed (${response.status}).`);
      try { return await response.json(); } catch { throw new Error('Coordinator returned invalid JSON.'); }
    } catch (error) {
      if (timedOut) throw new Error('Coordinator request timed out.');
      throw error;
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener('abort', abort);
    }
  }
  async tasks(signal: AbortSignal): Promise<FleetTask[]> {
    const result = await this.request('/tasks', signal);
    if (!record(result) || !Array.isArray(result.tasks)) throw new Error('Invalid coordinator task list.');
    return result.tasks.map(validateTask);
  }
  async detail(id: string, signal: AbortSignal): Promise<FleetTask> {
    const result = await this.request(`/tasks/${encodeURIComponent(id)}`, signal);
    return validateTask(record(result) && record(result.task) ? result.task : result);
  }
  async events(id: string, signal: AbortSignal): Promise<RecordValue[]> {
    const result = await this.request(`/tasks/${encodeURIComponent(id)}/events`, signal);
    if (!record(result) || !Array.isArray(result.events) || !result.events.every(record)) throw new Error('Invalid coordinator event list.');
    return result.events;
  }
  async fanout(id: string, signal: AbortSignal): Promise<FanoutPlan> {
    if (!TASK_ID.test(id)) throw new Error('Fanout requires a 32-character lowercase hex task id.');
    return validateFanoutPlan(await this.request(`/tasks/${id}/fanout`, signal, {}), id);
  }
}

export interface FleetBoard {element: HTMLElement; activate(): void; pause(clearCredentials?: boolean): void}
export function createFleetBoard(): FleetBoard {
  const element = document.createElement('section'); element.className = 'oc-card fleet-board'; element.setAttribute('aria-label', 'Hermes task board');
  function node<K extends keyof HTMLElementTagNameMap>(tag: K, text = ''): HTMLElementTagNameMap[K] { const el = document.createElement(tag); el.textContent = text; return el; }
  const heading = node('h3', 'Hermes · Fleet message board');
  const intro = node('p', 'Submit a development task to the Coding 01 pilot. Codex is the verified pilot runtime. Tasks continue on the worker when this board closes.');
  const status = node('p', 'Disconnected. Enter an operator token to connect.'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const connectForm = node('form'); connectForm.className = 'fleet-controls';
  const tokenLabel = node('label', 'Operator token'); const tokenInput = node('input'); tokenInput.type = 'password'; tokenInput.autocomplete = 'off'; tokenInput.spellcheck = false; tokenInput.required = true; tokenLabel.append(tokenInput);
  const connect = node('button', 'Connect'); connect.type = 'submit'; connect.className = 'oc-btn';
  const disconnect = node('button', 'Disconnect'); disconnect.type = 'button'; disconnect.className = 'oc-btn';
  connectForm.append(tokenLabel, connect, disconnect);
  const submitForm = node('form'); submitForm.className = 'fleet-submit';
  const titleLabel = node('label', 'Task title'); const title = node('input'); title.required = true; title.maxLength = 200; titleLabel.append(title);
  const briefLabel = node('label', 'Development request'); const brief = node('textarea'); brief.required = true; brief.maxLength = 12000; brief.rows = 4; briefLabel.append(brief);
  const submit = node('button', 'Submit to Coding 01'); submit.type = 'submit'; submit.disabled = true; submit.className = 'oc-btn oc-btn-primary';
  const scope = node('p', 'Project: snowgloves · Category: development · Runtime: codex');
  submitForm.append(titleLabel, briefLabel, scope, submit);
  const list = node('div'); list.className = 'fleet-task-list';
  const details = node('div'); details.className = 'fleet-task-details';
  element.append(heading, intro, status, connectForm, submitForm, list, details);
  let client: FleetClient | null = null, active = false, generation = 0, selected = '', busy = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const requests = new Set<AbortController>();
  const operationKey = () => crypto.randomUUID();
  let submissionKey = operationKey();
  const abortRequests = () => { generation++; clearTimeout(timer); requests.forEach(controller => controller.abort()); requests.clear(); busy = false; };
  const clearView = () => { list.replaceChildren(); details.replaceChildren(); };
  function failure(error: unknown) { clearView(); status.textContent = `Disconnected: ${error instanceof Error ? error.message : 'Request failed.'} No current task data.`; client = null; submit.disabled = true; abortRequests(); }
  async function request<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> { const controller = new AbortController(); requests.add(controller); try { return await operation(controller.signal); } finally { requests.delete(controller); } }
  const taskLabel = (task: FleetTask) => [task.title || task.id, task.status, task.logical_role, task.stage, task.organization || task.org || 'Organization unspecified', task.project, task.category, task.node || task.node_id || task.worker || 'Unassigned', task.runtime].map(displayValue).join(' · ');
  function renderDetail(task: FleetTask, events: RecordValue[]) {
    details.replaceChildren(node('h4', taskLabel(task)));
    const graph = graphLines(task);
    if (graph.length) { const panel = node('div'); panel.className = 'fleet-graph'; panel.append(node('h5', graph[0]), ...graph.slice(1).map(line => node('p', line))); details.append(panel); }
    const action = fanoutAction(task);
    if (action) {
      const actionPanel = node('div'); actionPanel.className = 'fleet-fanout-action';
      const actionStatus = node('p', action.reason);
      const fanout = node('button', 'Plan read-only roles'); fanout.type = 'button'; fanout.className = 'oc-btn';
      fanout.disabled = !action.available || action.planned || !client || !active;
      fanout.onclick = async () => {
        if (!client || !active || busy || !action.available || action.planned) return;
        const currentClient = client, selectedRoot = task.id, epoch = generation;
        busy = true; fanout.disabled = true;
        status.textContent = 'Planning read-only roles…';
        try {
          await request(signal => currentClient.fanout(selectedRoot, signal));
          if (epoch !== generation || !active || client !== currentClient || selected !== selectedRoot) return;
          busy = false;
          status.textContent = 'Read-only role plan accepted. Refreshing this task graph…';
          void refresh();
        } catch (error) {
          if (epoch === generation && active && client === currentClient && selected === selectedRoot) failure(error);
        } finally {
          if (epoch === generation) busy = false;
        }
      };
      actionPanel.append(actionStatus, fanout);
      details.append(actionPanel);
    }
    const openStates = ['queued', 'running', 'needs_input'];
    const openChildren = record(task.graph) && Array.isArray(task.graph.children)
      && task.graph.children.some(child => record(child) && openStates.includes(String(child.status)));
    const cancel = node('button', graph.length ? 'Cancel task and open children' : 'Cancel task'); cancel.className = 'oc-btn'; cancel.disabled = !openStates.includes(task.status) && !openChildren;
    cancel.onclick = async () => {
      if (!client || !active || busy || selected !== task.id || cancel.disabled) return;
      const epoch = generation; busy = true; cancel.disabled = true;
      try { await request(signal => client!.request(`/tasks/${encodeURIComponent(task.id)}/cancel`, signal, {})); if (epoch === generation) { busy = false; void refresh(); } } catch (error) { if (epoch === generation) failure(error); }
    };
    details.append(cancel);
    if (task.artifacts || task.artifact) details.append(node('pre', displayValue(task.artifacts || task.artifact)));
    const log = node('pre', events.length ? events.map(event => displayValue(event)).join('\n\n') : 'No events yet.'); log.setAttribute('aria-label', 'Task events and artifact receipts'); details.append(log);
  }
  async function refresh() {
    if (!active || !client || busy) return;
    const epoch = generation; busy = true; clearTimeout(timer);
    try {
      const currentClient = client;
      const tasks = await request(signal => currentClient.tasks(signal));
      let detail: FleetTask | null = null, events: RecordValue[] = [];
      if (selected) [detail, events] = await Promise.all([request(signal => currentClient.detail(selected, signal)), request(signal => currentClient.events(selected, signal))]);
      if (epoch !== generation || !active) return;
      list.replaceChildren(node('h4', 'Managed tasks'));
      if (!tasks.length) list.append(node('p', 'No managed tasks in your authorized scope.'));
      orderTasks(tasks).forEach(({task, child}) => { const button = node('button', taskLabel(task)); button.className = child ? 'oc-btn fleet-task fleet-task-child' : 'oc-btn fleet-task'; button.setAttribute('aria-pressed', String(selected === task.id)); button.onclick = () => { abortRequests(); selected = task.id; details.replaceChildren(); void refresh(); }; list.append(button); });
      if (detail) renderDetail(detail, events);
      status.textContent = 'Connected · Live coordinator records · Updates every 4 seconds';
    } catch (error) { if (epoch === generation) failure(error); }
    finally { if (epoch === generation) { busy = false; if (active && client) timer = setTimeout(() => void refresh(), 4000); } }
  }
  connectForm.onsubmit = event => { event.preventDefault(); abortRequests(); clearView(); selected = ''; try { client = new FleetClient(tokenInput.value); tokenInput.value = ''; submit.disabled = false; status.textContent = 'Connecting…'; void refresh(); } catch (error) { failure(error); } };
  disconnect.onclick = () => { abortRequests(); client = null; tokenInput.value = ''; submit.disabled = true; selected = ''; clearView(); status.textContent = 'Disconnected. Credentials cleared from this board.'; };
  submitForm.oninput = () => { submissionKey = operationKey(); };
  submitForm.onsubmit = async event => {
    event.preventDefault(); if (!client || !active || busy || !title.value.trim() || !brief.value.trim()) return;
    const epoch = generation; busy = true; submit.disabled = true;
    try {
      const result = await request(signal => client!.request('/tasks', signal, {project: 'snowgloves', title: title.value.trim(), brief: brief.value.trim(), category: 'development', runtime: 'codex', idempotency_key: submissionKey}));
      if (epoch !== generation) return;
      const task = validateTask(record(result) && record(result.task) ? result.task : result);
      selected = task.id; submissionKey = operationKey(); title.value = ''; brief.value = ''; busy = false; void refresh();
    } catch (error) { if (epoch === generation) failure(error); }
    finally { if (epoch === generation) { busy = false; submit.disabled = !client; } }
  };
  return {element, activate() { active = true; void refresh(); }, pause(clearCredentials = false) { active = false; abortRequests(); clearView(); tokenInput.value = ''; if (clearCredentials) { client = null; selected = ''; } submit.disabled = !client; status.textContent = client ? 'Paused. Reopen Hermes to refresh current records.' : 'Disconnected. Enter an operator token to connect.'; }};
}
