import './fleet-tasks.css';

type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue => typeof value === 'object' && value !== null && !Array.isArray(value);
export const FLEET_STATES = ['queued', 'running', 'cancel_requested', 'cancelled', 'succeeded', 'failed', 'interrupted', 'needs_input'] as const;
export type FleetTask = RecordValue & {id: string; status: typeof FLEET_STATES[number]};
export function validateTask(value: unknown): FleetTask {
  if (!record(value) || typeof value.id !== 'string' || !value.id || !FLEET_STATES.includes(value.status as typeof FLEET_STATES[number])) throw new Error('Invalid coordinator task response.');
  return value as FleetTask;
}
export function displayValue(value: unknown): string {
  if (value === undefined || value === null) return '—';
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
export class FleetClient {
  #token: string;
  constructor(token: string, private transport: typeof fetch = fetch) {
    if (!token.trim() || /[\r\n]/.test(token)) throw new Error('Enter a valid operator token.');
    this.#token = token.trim();
  }
  async request(path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
    if (!/^\/tasks(?:\/[^/?#]+(?:\/(?:events|cancel))?)?$/.test(path)) throw new Error('Unsupported fleet operation.');
    const response = await this.transport(`/api/fleet${path}`, {
      method: body === undefined ? 'GET' : 'POST', signal, cache: 'no-store', credentials: 'omit',
      headers: {Authorization: `Bearer ${this.#token}`, 'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
    });
    // Never display response bodies on errors: they can contain upstream credentials or prompts.
    if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? 'Access denied. Check your operator token and project permission.' : `Coordinator request failed (${response.status}).`);
    try { return await response.json(); } catch { throw new Error('Coordinator returned invalid JSON.'); }
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
  const taskLabel = (task: FleetTask) => [task.title || task.id, task.status, task.organization || task.org || 'Organization unspecified', task.project, task.category, task.node || task.node_id || task.worker || 'Unassigned', task.runtime].map(displayValue).join(' · ');
  function renderDetail(task: FleetTask, events: RecordValue[]) {
    details.replaceChildren(node('h4', taskLabel(task)));
    const cancel = node('button', 'Cancel task'); cancel.className = 'oc-btn'; cancel.disabled = !['queued', 'running', 'needs_input'].includes(task.status);
    cancel.onclick = async () => {
      if (!client || busy) return;
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
      tasks.forEach(task => { const button = node('button', taskLabel(task)); button.className = 'oc-btn fleet-task'; button.setAttribute('aria-pressed', String(selected === task.id)); button.onclick = () => { abortRequests(); selected = task.id; details.replaceChildren(); void refresh(); }; list.append(button); });
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
