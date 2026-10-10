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
export const CAPABILITY_STATES = ['executable', 'disabled', 'missing_configuration', 'unsupported', 'approval_required', 'refused'] as const;
export interface FleetWorker {id: string; node_id: string; access_modes: string[]; runtimes: string[]; availability: 'observed' | 'unobserved'}
export function eligibleWorkers(project: FleetProject | undefined): FleetWorker[] {
  return (project?.workers ?? []).filter(worker => worker.availability === 'observed' && worker.runtimes.includes('codex') && worker.access_modes.includes('read'));
}
export interface FleetProject {id: string; tenant: string; organization: string; runtimes: string[]; workers: FleetWorker[]}
export interface FleetContext {projects: FleetProject[]; permissions: string[]}
export interface FleetCapability {id: string; name: string; project: string; tenant: string; state: typeof CAPABILITY_STATES[number]; reason: string; input_schema?: RecordValue}
export interface FleetApproval {id: string; project: string; capability_id: string; status: string; request_digest: string; inputs?: RecordValue; tenant?: string; owner?: string; worker_id?: string | null}
export interface FleetArtifact {sha256: string; content: unknown}
export function validateContext(value: unknown): FleetContext {
  if (!record(value) || !Array.isArray(value.projects) || !Array.isArray(value.permissions)
      || !value.permissions.every(item => typeof item === 'string')
      || !value.projects.every(project => record(project) && typeof project.id === 'string' && !!project.id
        && typeof project.tenant === 'string' && typeof project.organization === 'string'
        && Array.isArray(project.runtimes) && project.runtimes.every(item => typeof item === 'string')
        && Array.isArray(project.workers) && project.workers.every(worker => record(worker)
          && typeof worker.id === 'string' && typeof worker.node_id === 'string'
          && Array.isArray(worker.access_modes) && worker.access_modes.every(item => typeof item === 'string')
          && Array.isArray(worker.runtimes) && worker.runtimes.every(item => typeof item === 'string')
          && ['observed', 'unobserved'].includes(String(worker.availability))))
      || new Set(value.projects.map(project => project.id)).size !== value.projects.length) throw new Error('Invalid coordinator context.');
  return value as unknown as FleetContext;
}
export function validateCapabilities(value: unknown): FleetCapability[] {
  if (!record(value) || !Array.isArray(value.capabilities) || !value.capabilities.every(item => record(item)
      && ['id', 'name', 'project', 'tenant', 'reason'].every(key => typeof item[key] === 'string')
      && CAPABILITY_STATES.includes(item.state as typeof CAPABILITY_STATES[number])
      && (['executable', 'approval_required'].includes(String(item.state)) ? record(item.input_schema)
        : item.input_schema === undefined || record(item.input_schema)))) throw new Error('Invalid capability catalog.');
  return value.capabilities as unknown as FleetCapability[];
}
export function validateApprovals(value: unknown): FleetApproval[] {
  if (!record(value) || !Array.isArray(value.approvals) || !value.approvals.every(item => record(item)
      && typeof item.id === 'string' && TASK_ID.test(item.id)
      && ['project', 'capability_id', 'status', 'request_digest'].every(key => typeof item[key] === 'string'))) throw new Error('Invalid approval list.');
  return value.approvals as unknown as FleetApproval[];
}
export function validateArtifact(value: unknown): FleetArtifact {
  if (!record(value) || !record(value.artifact) || typeof value.artifact.sha256 !== 'string'
      || !/^[a-f0-9]{64}$/.test(value.artifact.sha256) || !record(value.artifact.content)) throw new Error('Invalid task artifact.');
  return value.artifact as unknown as FleetArtifact;
}
export class FleetClient {
  #token: string;
  constructor(token: string, private transport: typeof fetch = (input, init) => fetch(input, init)) {
    if (!token.trim() || /[\r\n]/.test(token)) throw new Error('Enter a valid operator token.');
    this.#token = token.trim();
  }
  async request(path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
    const method = body === undefined ? 'GET' : 'POST';
    const getAllowed = ['/tasks', '/context', '/capabilities', '/approvals'].includes(path) || /^\/tasks\/[^/?#]+(?:\/(?:events|artifact))?$/.test(path);
    const postAllowed = ['/tasks', '/capabilities/execute', '/approvals'].includes(path) || /^\/tasks\/[^/?#]+\/(?:cancel|fanout)$/.test(path) || /^\/approvals\/[a-f0-9]{32}\/(?:approve|reject)$/.test(path);
    if ((method === 'GET' && !getAllowed) || (method === 'POST' && !postAllowed)) throw new Error('Unsupported fleet operation.');
    if (path.endsWith('/fanout') && (!record(body) || Object.keys(body).length)) throw new Error('Fanout accepts no options.');
    const encoded = body === undefined ? undefined : JSON.stringify(body);
    if (encoded !== undefined && new TextEncoder().encode(encoded).byteLength > MAX_FLEET_BODY_BYTES) throw new Error('Fleet request body is too large.');
    const bounded = new AbortController();
    let timedOut = false;
    const abort = () => bounded.abort();
    signal.addEventListener('abort', abort, {once: true});
    if (signal.aborted) bounded.abort();
    const planning = method === 'POST' && (path === '/tasks' || path === '/capabilities/execute' || path.endsWith('/fanout'));
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
  async context(signal: AbortSignal): Promise<FleetContext> { return validateContext(await this.request('/context', signal)); }
  async capabilities(signal: AbortSignal): Promise<FleetCapability[]> { return validateCapabilities(await this.request('/capabilities', signal)); }
  async approvals(signal: AbortSignal): Promise<FleetApproval[]> { return validateApprovals(await this.request('/approvals', signal)); }
  async artifact(id: string, signal: AbortSignal): Promise<FleetArtifact> {
    return validateArtifact(await this.request(`/tasks/${encodeURIComponent(id)}/artifact`, signal));
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
  const intro = node('p', 'Hermes orchestrates managed work on your authorized fleet. Grok Bot and this board share coordinator task records. Tasks continue when this board closes.');
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
  const projectLabel = node('label', 'Tenant / project'); const projectSelect = node('select'); projectSelect.disabled = true; projectLabel.append(projectSelect);
  const workerLabel = node('label', 'Execution node'); const workerSelect = node('select'); workerSelect.disabled = true; workerLabel.append(workerSelect);
  submitForm.append(projectLabel, workerLabel, titleLabel, briefLabel, scope, submit);
  const catalogPanel = node('section'); catalogPanel.className = 'fleet-catalog'; catalogPanel.setAttribute('aria-label', 'Capability catalog');
  const capabilityLabel = node('label', 'Catalog capability'); const capabilitySelect = node('select'); capabilitySelect.disabled = true; capabilityLabel.append(capabilitySelect);
  const capabilityState = node('p', 'Connect to inspect catalog readiness.'); capabilityState.setAttribute('role', 'status');
  const schema = node('pre'); schema.setAttribute('aria-label', 'Capability input schema');
  const inputLabel = node('label', 'Capability inputs (JSON object)'); const capabilityInputs = node('textarea'); capabilityInputs.value = '{}'; capabilityInputs.rows = 5; capabilityInputs.maxLength = 16000; capabilityInputs.spellcheck = false; inputLabel.append(capabilityInputs);
  const approvalLabel = node('label', 'Approved request'); const approvalSelect = node('select'); approvalLabel.append(approvalSelect);
  const execute = node('button', 'Execute capability'); execute.type = 'button'; execute.className = 'oc-btn oc-btn-primary'; execute.disabled = true;
  const requestApproval = node('button', 'Request approval'); requestApproval.type = 'button'; requestApproval.className = 'oc-btn'; requestApproval.disabled = true;
  const catalogStatus = node('p'); catalogStatus.setAttribute('role', 'status'); catalogStatus.setAttribute('aria-live', 'polite');
  const catalogRows = node('div'); catalogRows.className = 'fleet-catalog-rows';
  const approvalsPanel = node('section'); approvalsPanel.className = 'fleet-approvals'; approvalsPanel.setAttribute('aria-label', 'Capability approvals');
  catalogPanel.append(node('h4', 'Capability catalog'), capabilityLabel, capabilityState, schema, inputLabel, approvalLabel, execute, requestApproval, catalogStatus, catalogRows);

  const list = node('div'); list.className = 'fleet-task-list';
  const details = node('div'); details.className = 'fleet-task-details';
  element.append(heading, intro, status, connectForm, submitForm, catalogPanel, approvalsPanel, list, details);
  let client: FleetClient | null = null, active = false, generation = 0, selected = '', busy = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const requests = new Set<AbortController>();
  const operationKey = () => crypto.randomUUID();
  let submissionKey = operationKey(), capabilityKey = operationKey();
  let context: FleetContext | null = null, capabilities: FleetCapability[] = [], approvals: FleetApproval[] = [];
  const detailActions = new Map<HTMLButtonElement, () => boolean>();
  let artifactUrl: string | null = null, loadedArtifact: {taskId: string; artifact: FleetArtifact} | null = null;
  let preferredProject = '', preferredWorker = '', preferredCapability = '';
  const revokeArtifact = () => { if (artifactUrl) URL.revokeObjectURL(artifactUrl); artifactUrl = null; };
  const selectedProject = () => context?.projects.find(item => item.id === projectSelect.value);
  const selectedCapability = () => capabilities.find(item => item.id === capabilitySelect.value && item.project === projectSelect.value);
  const permission = (name: string) => context?.permissions.includes(name) === true;
  function updateActions() {
    const ready = !!client && !!context && active;
    submit.disabled = !ready || !permission('submit') || !selectedProject()?.runtimes.includes('codex') || !eligibleWorkers(selectedProject()).length || busy;
    projectSelect.disabled = !ready || busy; workerSelect.disabled = !ready || busy;
    title.disabled = !ready || busy; brief.disabled = !ready || busy; capabilityInputs.disabled = !ready || busy; approvalSelect.disabled = !ready || busy;
    capabilitySelect.disabled = !ready || busy || !capabilities.some(item => item.project === projectSelect.value);
    const cap = selectedCapability();
    const workerReady = eligibleWorkers(selectedProject()).length > 0;
    execute.disabled = !ready || busy || !permission('submit') || !workerReady || !cap
      || !(cap.state === 'executable' || cap.state === 'approval_required' && !!approvalSelect.value);
    requestApproval.disabled = !ready || busy || !permission('submit') || !workerReady || cap?.state !== 'approval_required';
    detailActions.forEach((eligible, button) => { button.disabled = !ready || busy || !eligible(); });
  }
  function detailAction(button: HTMLButtonElement, eligible: () => boolean) { detailActions.set(button, eligible); button.disabled = busy || !active || !client || !eligible(); }
  function options(select: HTMLSelectElement, entries: {value: string; label: string}[], preferred = select.value) {
    select.replaceChildren(...entries.map(item => { const option = node('option', item.label); option.value = item.value; return option; }));
    select.value = entries.some(item => item.value === preferred) ? preferred : entries[0]?.value ?? '';
  }
  function renderCapability() {
    const cap = selectedCapability();
    capabilityState.textContent = cap ? `${cap.name} · ${cap.state.replaceAll('_', ' ')} · ${cap.reason}` : 'No capabilities available in this project.';
    schema.textContent = cap?.input_schema ? displayValue(cap.input_schema) : 'No executable input schema. Resolve the listed prerequisites.';
    options(approvalSelect, [{value: '', label: 'No approval selected'}, ...approvals.filter(item => item.project === projectSelect.value && item.capability_id === cap?.id && item.status === 'approved').map(item => ({value: item.id, label: `${item.id} · ${item.request_digest}`}))]);
    updateActions();
  }
  function renderCatalog() {
    options(capabilitySelect, capabilities.filter(item => item.project === projectSelect.value).map(item => ({value: item.id, label: `${item.name} · ${item.state.replaceAll('_', ' ')}`})), preferredCapability || capabilitySelect.value);
    preferredCapability = capabilitySelect.value;
    catalogRows.replaceChildren(...capabilities.filter(item => item.project === projectSelect.value).map(item => node('p', `${item.name} · ${item.state.replaceAll('_', ' ')} · ${item.reason}`)));
    renderCapability();
    approvalsPanel.replaceChildren(node('h4', 'Approval requests'));
    if (!approvals.length) approvalsPanel.append(node('p', 'No approval requests in your authorized scope.'));
    approvals.forEach(item => {
      const row = node('div'); row.className = 'fleet-approval';
      row.append(node('p', `${item.project} · ${item.capability_id} · ${item.status} · ${item.id}`), node('p', `Reviewed request digest: ${item.request_digest}`));
      row.append(node('p', `Tenant: ${item.tenant ?? 'unspecified'} · Requester: ${item.owner ?? 'unspecified'} · Worker: ${item.worker_id ?? 'automatic eligible node'}`));
      const input = item.inputs;
      if (record(input)) row.append(node('pre', displayValue(input)));
      if (permission('approve') && item.status === 'pending' && record(input)) {
        for (const decision of ['approve', 'reject'] as const) {
          const button = node('button', decision === 'approve' ? 'Approve reviewed request' : 'Reject request'); button.type = 'button'; button.className = 'oc-btn';
          button.onclick = async () => {
            if (!client || !active || busy || !permission('approve') || !approvals.some(current => current.id === item.id && current.status === 'pending')) return;
            const epoch = generation, currentClient = client; busy = true; button.disabled = true; updateActions();
            try { await request(signal => currentClient.request(`/approvals/${item.id}/${decision}`, signal, {})); if (epoch === generation) { busy = false; void refresh(); } }
            catch (error) { if (epoch === generation) failure(error); }
          };
          row.append(button);
        }
      }
      approvalsPanel.append(row);
    });
  }
  function renderContext() {
    options(projectSelect, (context?.projects ?? []).map(item => ({value: item.id, label: `${item.organization} · ${item.tenant} / ${item.id}`})), preferredProject || projectSelect.value);
    preferredProject = projectSelect.value;
    const project = selectedProject();
    const workers = eligibleWorkers(project), priorWorker = preferredWorker || workerSelect.value;
    options(workerSelect, [{value: '', label: workers.length ? 'Automatic observed eligible node' : 'No observed eligible node'}, ...workers.map(item => ({value: item.id, label: `${item.node_id} · observed · ${item.access_modes.join(', ')}`}))], priorWorker);
    preferredWorker = workerSelect.value;
    if (priorWorker !== preferredWorker) { submissionKey = operationKey(); capabilityKey = operationKey(); approvalSelect.value = ''; }
    scope.textContent = `Project: ${project?.id ?? 'none'} · Category: development · Runtime: codex · Observed eligible nodes: ${workers.length} · Configured unobserved nodes: ${(project?.workers ?? []).filter(item => item.availability === 'unobserved').length}`;
    renderCatalog();
  }

  const abortRequests = () => { generation++; clearTimeout(timer); requests.forEach(controller => controller.abort()); requests.clear(); busy = false; };
  const clearView = () => { detailActions.clear(); revokeArtifact(); loadedArtifact = null; list.replaceChildren(); details.replaceChildren(); catalogRows.replaceChildren(); approvalsPanel.replaceChildren(); context = null; capabilities = []; approvals = []; projectSelect.replaceChildren(); workerSelect.replaceChildren(); capabilitySelect.replaceChildren(); approvalSelect.replaceChildren(); schema.textContent = ''; capabilityState.textContent = 'Connect to inspect catalog readiness.'; updateActions(); };
  function failure(error: unknown) { clearView(); status.textContent = `Disconnected: ${error instanceof Error ? error.message : 'Request failed.'} No current task data.`; client = null; submit.disabled = true; abortRequests(); updateActions(); }
  async function request<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> { const controller = new AbortController(); requests.add(controller); try { return await operation(controller.signal); } finally { requests.delete(controller); } }
  const taskLabel = (task: FleetTask) => [task.title || task.id, task.status, task.logical_role, task.stage, task.organization || task.org || 'Organization unspecified', task.project, task.category, task.node || task.node_id || task.worker || 'Unassigned', task.runtime].map(displayValue).join(' · ');
  function renderDetail(task: FleetTask, events: RecordValue[]) {
    if (loadedArtifact?.taskId !== task.id) { revokeArtifact(); loadedArtifact = null; }
    detailActions.clear(); details.replaceChildren(node('h4', taskLabel(task)), node('p', `Task ID: ${task.id}`));
    const graph = graphLines(task);
    if (graph.length) { const panel = node('div'); panel.className = 'fleet-graph'; panel.append(node('h5', graph[0]), ...graph.slice(1).map(line => node('p', line))); details.append(panel); }
    const action = fanoutAction(task);
    if (action) {
      const actionPanel = node('div'); actionPanel.className = 'fleet-fanout-action';
      const actionStatus = node('p', action.reason);
      const fanout = node('button', 'Plan read-only roles'); fanout.type = 'button'; fanout.className = 'oc-btn';
      detailAction(fanout, () => action.available && !action.planned && selected === task.id);
      fanout.onclick = async () => {
        if (!client || !active || busy || !action.available || action.planned) return;
        const currentClient = client, selectedRoot = task.id, epoch = generation;
        let shouldRefresh = false; busy = true; updateActions();
        status.textContent = 'Planning read-only roles…';
        try {
          await request(signal => currentClient.fanout(selectedRoot, signal));
          if (epoch !== generation || !active || client !== currentClient || selected !== selectedRoot) return;
          status.textContent = 'Read-only role plan accepted. Refreshing this task graph…';
          shouldRefresh = true;
        } catch (error) {
          if (epoch === generation && active && client === currentClient && selected === selectedRoot) failure(error);
        } finally {
          if (epoch === generation) { busy = false; updateActions(); if (shouldRefresh) void refresh(); }
        }
      };
      actionPanel.append(actionStatus, fanout);
      details.append(actionPanel);
    }
    const openStates = ['queued', 'running', 'needs_input'];
    const openChildren = record(task.graph) && Array.isArray(task.graph.children)
      && task.graph.children.some(child => record(child) && openStates.includes(String(child.status)));
    const cancel = node('button', graph.length ? 'Cancel task and open children' : 'Cancel task'); cancel.className = 'oc-btn';
    detailAction(cancel, () => permission('cancel') && (openStates.includes(task.status) || !!openChildren) && selected === task.id);
    cancel.onclick = async () => {
      if (!client || !active || busy || selected !== task.id || cancel.disabled) return;
      const epoch = generation; busy = true; updateActions();
      try { await request(signal => client!.request(`/tasks/${encodeURIComponent(task.id)}/cancel`, signal, {})); if (epoch === generation) { busy = false; void refresh(); } } catch (error) { if (epoch === generation) failure(error); }
    };
    details.append(cancel);
    if (task.artifacts || task.artifact) {
      details.append(node('pre', displayValue(task.artifacts || task.artifact)));
      const showArtifact = node('button', 'Read verified result'); showArtifact.type = 'button'; showArtifact.className = 'oc-btn';
      const artifactPanel = node('div'); artifactPanel.className = 'fleet-artifact';
      detailAction(showArtifact, () => selected === task.id);
      const renderArtifact = (artifact: FleetArtifact) => {
        artifactPanel.replaceChildren(node('p', `Source artifact SHA-256 (verified by coordinator): ${artifact.sha256}`), node('pre', displayValue(artifact.content)));
        if (!artifactUrl) artifactUrl = URL.createObjectURL(new Blob([JSON.stringify(artifact.content, null, 2)], {type: 'application/json'}));
        const download = node('a', 'Download safe artifact JSON'); download.href = artifactUrl; download.download = `fleet-${task.id}.json`; artifactPanel.append(download);
      };
      if (loadedArtifact?.taskId === task.id) renderArtifact(loadedArtifact.artifact);
      showArtifact.onclick = async () => {
        if (!client || !active || busy || selected !== task.id) return;
        const currentClient = client, epoch = generation; busy = true; updateActions();
        try {
          const artifact = await request(signal => currentClient.artifact(task.id, signal));
          if (epoch !== generation || !active || selected !== task.id) return;
          revokeArtifact(); loadedArtifact = {taskId: task.id, artifact}; renderArtifact(artifact);
        } catch (error) { if (epoch === generation) artifactPanel.replaceChildren(node('p', error instanceof Error ? error.message : 'Artifact unavailable.')); }
        finally { if (epoch === generation) { busy = false; updateActions(); } }
      };
      details.append(showArtifact, artifactPanel);
    }
    const log = node('pre', events.length ? events.map(event => displayValue(event)).join('\n\n') : 'No events yet.'); log.setAttribute('aria-label', 'Task events and artifact receipts'); details.append(log);
  }
  async function refresh() {
    if (!active || !client || busy) return;
    const epoch = generation; busy = true; updateActions(); clearTimeout(timer);
    try {
      const currentClient = client;
      const [tasks, nextContext, nextCapabilities, nextApprovals] = await Promise.all([
        request(signal => currentClient.tasks(signal)), request(signal => currentClient.context(signal)),
        request(signal => currentClient.capabilities(signal)), request(signal => currentClient.approvals(signal)),
      ]);
      if (epoch !== generation || !active) return;
      context = nextContext; capabilities = nextCapabilities; approvals = nextApprovals;
      renderContext();
      let detail: FleetTask | null = null, events: RecordValue[] = [];
      if (selected) [detail, events] = await Promise.all([request(signal => currentClient.detail(selected, signal)), request(signal => currentClient.events(selected, signal))]);
      if (epoch !== generation || !active) return;
      list.replaceChildren(node('h4', 'Managed tasks'));
      if (!tasks.length) list.append(node('p', 'No managed tasks in your authorized scope.'));
      orderTasks(tasks).forEach(({task, child}) => { const button = node('button', taskLabel(task)); button.className = child ? 'oc-btn fleet-task fleet-task-child' : 'oc-btn fleet-task'; button.setAttribute('aria-pressed', String(selected === task.id)); button.onclick = () => { abortRequests(); selected = task.id; details.replaceChildren(); void refresh(); }; list.append(button); });
      if (detail) renderDetail(detail, events);
      status.textContent = 'Connected · Live coordinator records · Updates every 4 seconds';
    } catch (error) { if (epoch === generation) failure(error); }
    finally { if (epoch === generation) { busy = false; updateActions(); if (active && client) timer = setTimeout(() => void refresh(), 4000); } }
  }
  connectForm.onsubmit = event => { event.preventDefault(); abortRequests(); clearView(); selected = ''; try { client = new FleetClient(tokenInput.value); tokenInput.value = ''; submit.disabled = true; status.textContent = 'Connecting…'; void refresh(); } catch (error) { failure(error); } };
  disconnect.onclick = () => { abortRequests(); client = null; tokenInput.value = ''; submit.disabled = true; selected = ''; clearView(); status.textContent = 'Disconnected. Credentials cleared from this board.'; };
  submitForm.oninput = () => { submissionKey = operationKey(); };
  submitForm.onsubmit = async event => {
    event.preventDefault(); if (!client || !active || busy || submit.disabled || !title.value.trim() || !brief.value.trim()) return;
    const epoch = generation; let shouldRefresh = false; busy = true; updateActions();
    try {
      const result = await request(signal => client!.request('/tasks', signal, {project: projectSelect.value, ...(workerSelect.value ? {worker_id: workerSelect.value} : {}), title: title.value.trim(), brief: brief.value.trim(), category: 'development', runtime: 'codex', idempotency_key: submissionKey}));
      if (epoch !== generation) return;
      const task = validateTask(record(result) && record(result.task) ? result.task : result);
      selected = task.id; submissionKey = operationKey(); title.value = ''; brief.value = ''; shouldRefresh = true;
    } catch (error) { if (epoch === generation) failure(error); }
    finally { if (epoch === generation) { busy = false; updateActions(); if (shouldRefresh) void refresh(); } }
  };
  projectSelect.onchange = () => { preferredProject = projectSelect.value; preferredWorker = ''; preferredCapability = ''; submissionKey = operationKey(); capabilityKey = operationKey(); capabilityInputs.value = '{}'; catalogStatus.textContent = ''; renderContext(); };
  workerSelect.onchange = () => { preferredWorker = workerSelect.value; submissionKey = operationKey(); capabilityKey = operationKey(); approvalSelect.value = ''; updateActions(); };
  capabilitySelect.onchange = () => { preferredCapability = capabilitySelect.value; capabilityKey = operationKey(); capabilityInputs.value = '{}'; catalogStatus.textContent = ''; renderCapability(); };
  capabilityInputs.oninput = () => { capabilityKey = operationKey(); approvalSelect.value = ''; catalogStatus.textContent = ''; updateActions(); };
  approvalSelect.onchange = () => { capabilityKey = operationKey(); updateActions(); };
  async function capabilityOperation(approval: boolean) {
    const cap = selectedCapability();
    if (!client || !active || busy || !cap || (approval ? requestApproval.disabled : execute.disabled)) return;
    let inputs: RecordValue;
    try { const parsed: unknown = JSON.parse(capabilityInputs.value); if (!record(parsed)) throw new Error(); inputs = parsed; }
    catch { catalogStatus.textContent = 'Inputs must be a valid JSON object.'; return; }
    const epoch = generation, currentClient = client; let shouldRefresh = false; busy = true; updateActions();
    const body = {project: projectSelect.value, capability_id: cap.id, inputs, idempotency_key: capabilityKey, ...(workerSelect.value ? {worker_id: workerSelect.value} : {}), ...(!approval && approvalSelect.value ? {approval_id: approvalSelect.value} : {})};
    catalogStatus.textContent = approval ? 'Requesting review…' : 'Submitting capability…';
    try {
      const result = await request(signal => currentClient.request(approval ? '/approvals' : '/capabilities/execute', signal, body));
      if (epoch !== generation || !active || currentClient !== client) return;
      if (!approval) { const task = validateTask(record(result) && record(result.task) ? result.task : result); selected = task.id; }
      else validateApprovals({approvals: [record(result) ? result.approval : null]});
      capabilityKey = operationKey(); catalogStatus.textContent = approval ? 'Approval requested. Review the exact inputs before deciding.' : 'Capability task accepted. Follow its managed task record.';
      shouldRefresh = true;
    } catch (error) {
      if (epoch === generation) catalogStatus.textContent = `${error instanceof Error ? error.message : 'Request failed.'} Retry unchanged inputs with the same submission key; the coordinator prevents duplicate work.`;
    } finally { if (epoch === generation) { busy = false; updateActions(); if (shouldRefresh) void refresh(); } }
  }
  execute.onclick = () => capabilityOperation(false);
  requestApproval.onclick = () => capabilityOperation(true);
  return {element, activate() { active = true; void refresh(); }, pause(clearCredentials = false) { active = false; abortRequests(); clearView(); tokenInput.value = ''; if (clearCredentials) { client = null; selected = ''; } updateActions(); status.textContent = client ? 'Paused. Reopen Hermes to refresh current records.' : 'Disconnected. Enter an operator token to connect.'; }};
}
