import {RESIDENTS, type ResidentSlug} from './residents';
import type {FleetClient} from './fleet-tasks';

export type AskKind = 'fact' | 'decision' | 'connect' | 'website' | 'brand';
export interface TenantAsk {
  id: string;
  project: string;
  tenant: string;
  kind: AskKind;
  role: ResidentSlug;
  title: string;
  source: string;
  answerType: 'text' | 'yes_no';
  proposed: string | null;
  status: 'open' | 'answered';
  answer: {value: string} | {accept: boolean} | null;
}

const KINDS = ['fact', 'decision', 'connect', 'website', 'brand'] as const;
const ROLE_FOR_KIND: Record<AskKind, ResidentSlug> = {
  fact: 'librarian',
  decision: 'chief-of-staff',
  connect: 'dispatcher',
  website: 'interpreter',
  brand: 'interpreter',
};
const ROLES = new Set<string>(RESIDENTS.map(resident => resident.slug));
const ASK_ID = /^[a-f0-9]{32}$/;
const PROJECT_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;
// Mirrors Capabilities.project(): `_demo` or [A-Za-z0-9][A-Za-z0-9_.-]{0,99}.
const TENANT_ID = /^(?:_demo|[A-Za-z0-9][A-Za-z0-9_.-]{0,99})$/;
const ASK_KEYS = new Set(['id', 'project', 'tenant', 'kind', 'role', 'title', 'source', 'answer_type', 'proposed', 'status', 'answer', 'answered', 'answered_by']);
const REQUIRED_KEYS = ['id', 'project', 'tenant', 'kind', 'role', 'title', 'source', 'answer_type', 'proposed', 'status', 'answer'];

function fail(field: string): never {
  throw new Error(`Invalid tenant asks: ${field}.`);
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function plain(value: unknown, max: number, field: string): string {
  if (typeof value !== 'string' || value.length < 1 || value.length > max || /[\u0000-\u001f]/.test(value)) fail(field);
  return value;
}
function parseAnswer(raw: unknown, answerType: TenantAsk['answerType'], status: TenantAsk['status']): TenantAsk['answer'] {
  if (status === 'open') {
    if (raw !== null) fail('answer');
    return null;
  }
  if (!record(raw) || Object.keys(raw).length !== 1) fail('answer');
  if (answerType === 'yes_no') {
    if (typeof raw.accept !== 'boolean' || Object.keys(raw)[0] !== 'accept') fail('answer');
    return {accept: raw.accept};
  }
  if (Object.keys(raw)[0] !== 'value') fail('answer');
  return {value: plain(raw.value, 500, 'answer')};
}
function parseAsk(raw: unknown, project: string): TenantAsk {
  if (!record(raw)) fail('ask');
  for (const key of Object.keys(raw)) if (!ASK_KEYS.has(key)) fail(key);
  for (const key of REQUIRED_KEYS) if (!Object.hasOwn(raw, key)) fail(key);
  if (raw.project !== project || !PROJECT_ID.test(project)) fail('project');
  const id = plain(raw.id, 32, 'id');
  if (!ASK_ID.test(id)) fail('id');
  const tenant = plain(raw.tenant, 100, 'tenant');
  if (!TENANT_ID.test(tenant)) fail('tenant');
  if (typeof raw.kind !== 'string' || !(KINDS as readonly string[]).includes(raw.kind)) fail('kind');
  const kind = raw.kind as AskKind;
  if (typeof raw.role !== 'string' || !ROLES.has(raw.role)) fail('role');
  const role = raw.role as ResidentSlug;
  if (role !== ROLE_FOR_KIND[kind]) fail('role');
  if (raw.answer_type !== 'text' && raw.answer_type !== 'yes_no') fail('answer_type');
  if (raw.status !== 'open' && raw.status !== 'answered') fail('status');
  const proposed = raw.proposed === null ? null : plain(raw.proposed, 500, 'proposed');
  if ('answered' in raw && raw.answered !== null && (typeof raw.answered !== 'number' || !Number.isFinite(raw.answered))) fail('answered');
  if ('answered_by' in raw && raw.answered_by !== null && (typeof raw.answered_by !== 'string' || !plain(raw.answered_by, 120, 'answered_by'))) fail('answered_by');
  if (raw.status === 'open' && (raw.answered != null || raw.answered_by != null)) fail('status');
  return {
    id, project, tenant, kind, role, title: plain(raw.title, 160, 'title'), source: plain(raw.source, 240, 'source'),
    answerType: raw.answer_type, proposed, status: raw.status, answer: parseAnswer(raw.answer, raw.answer_type, raw.status),
  };
}
export function parseAsks(raw: unknown, project: string): TenantAsk[] {
  if (!PROJECT_ID.test(project)) fail('project');
  if (!record(raw) || Object.keys(raw).some(key => key !== 'asks') || !Array.isArray(raw.asks) || raw.asks.length > 400) fail('asks');
  const asks = raw.asks.map(item => parseAsk(item, project));
  if (new Set(asks.map(ask => ask.id)).size !== asks.length) fail('id');
  return asks;
}
export function summarizeAsks(asks: TenantAsk[]): {byTenant: Record<string, number>; byRole: Partial<Record<ResidentSlug, number>>} {
  const byTenant: Record<string, number> = {};
  const byRole: Partial<Record<ResidentSlug, number>> = {};
  for (const ask of asks) {
    if (ask.status !== 'open') continue;
    byTenant[ask.tenant] = (byTenant[ask.tenant] ?? 0) + 1;
    byRole[ask.role] = (byRole[ask.role] ?? 0) + 1;
  }
  return {byTenant, byRole};
}

export function renderAskStack(asks: TenantAsk[], onAnswer: (ask: TenantAsk, answer: {value: string} | {accept: boolean}) => Promise<void>): HTMLElement {
  const stack = document.createElement('section');
  stack.className = 'oc-asks';
  stack.setAttribute('aria-label', 'Founder asks');
  async function submit(card: HTMLElement, controls: HTMLButtonElement[], ask: TenantAsk, answer: {value: string} | {accept: boolean}): Promise<void> {
    if (controls.some(control => control.disabled)) return;
    for (const control of controls) control.disabled = true;
    for (const child of Array.from(card.children)) if (child.className === 'oc-asks-error') child.remove();
    try {
      await onAnswer(ask, answer);
    } catch (error) {
      const note = document.createElement('p');
      note.className = 'oc-asks-error';
      note.setAttribute('role', 'alert');
      note.textContent = error instanceof Error && error.message.trim() ? error.message : 'Coordinator rejected the answer.';
      card.append(note);
      for (const control of controls) control.disabled = false;
    }
  }
  if (!asks.length) {
    const empty = document.createElement('p');
    empty.className = 'oc-asks-empty';
    empty.textContent = 'No asks waiting.';
    stack.append(empty);
    return stack;
  }
  const ordered = [...asks.filter(ask => ask.status === 'open'), ...asks.filter(ask => ask.status !== 'open')];
  for (const ask of ordered) {
    const card = document.createElement('article');
    card.className = 'oc-asks-card';
    const title = document.createElement('h3');
    title.className = 'oc-asks-title';
    title.textContent = ask.title;
    const meta = document.createElement('p');
    meta.className = 'oc-asks-meta';
    meta.textContent = `${ask.kind} · ${ask.role} · ${ask.source}`;
    card.append(title, meta);
    // An answered ask shows its answer; its controls stay hidden until the founder chooses to change it.
    const appendControls = (controls: HTMLElement) => {
      if (ask.status !== 'answered' || !ask.answer) { card.append(controls); return; }
      const shown = document.createElement('p');
      shown.className = 'oc-asks-answer';
      shown.textContent = `Answered: ${'accept' in ask.answer ? (ask.answer.accept ? 'Yes' : 'No') : ask.answer.value}`;
      const change = document.createElement('button');
      change.type = 'button';
      change.className = 'oc-asks-btn';
      change.textContent = 'Change answer';
      controls.hidden = true;
      change.onclick = () => { controls.hidden = false; change.remove(); };
      card.append(shown, change, controls);
    };
    if (ask.proposed) {
      const proposed = document.createElement('p');
      proposed.className = 'oc-asks-proposed';
      proposed.textContent = ask.proposed;
      card.append(proposed);
    }
    if (ask.answerType === 'yes_no') {
      const actions = document.createElement('div');
      actions.className = 'oc-asks-actions';
      const controls: HTMLButtonElement[] = [];
      for (const choice of [{label: 'Yes', accept: true}, {label: 'No', accept: false}] as const) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'oc-asks-btn';
        button.textContent = choice.label;
        button.onclick = () => submit(card, controls, ask, {accept: choice.accept});
        controls.push(button);
        actions.append(button);
      }
      appendControls(actions);
    } else {
      const form = document.createElement('form');
      form.className = 'oc-asks-form';
      const input = document.createElement('input');
      input.className = 'oc-asks-input';
      input.type = 'text';
      input.maxLength = 500;
      input.setAttribute('maxlength', '500');
      const send = document.createElement('button');
      send.type = 'submit';
      send.className = 'oc-asks-btn';
      send.textContent = 'Send';
      const controls = [send];
      form.append(input, send);
      form.onsubmit = event => {
        event.preventDefault();
        const value = input.value;
        if (!value.trim() || value.length > 500) return;
        return submit(card, controls, ask, {value});
      };
      appendControls(form);
    }
    stack.append(card);
  }
  return stack;
}

/** Poll open asks for the connected projects. A failed poll keeps the last list. The stop function clears them. */
export function startAskSync(client: FleetClient, projects: string[], emit: (asks: TenantAsk[] | null) => void, intervalMs = 60000): () => void {
  let stopped = false;
  let generation = 0;
  // Only ids the asks route accepts are polled; each project fails on its own.
  const routable = projects.filter(project => /^[a-z0-9][a-z0-9_-]{0,63}$/.test(project));
  const lastGood = new Map<string, TenantAsk[]>();
  const pull = () => {
    if (stopped) return;
    const epoch = ++generation;
    void (async () => {
      const results = await Promise.allSettled(routable.map(project => client.asks(project)));
      if (stopped || epoch !== generation) return;
      // If every poll failed, keep the last good list. Only stop() emits null.
      if (!results.some(result => result.status === 'fulfilled')) return;
      results.forEach((result, index) => { if (result.status === 'fulfilled') lastGood.set(routable[index], result.value); });
      emit(routable.flatMap(project => lastGood.get(project) ?? []));
    })();
  };
  pull();
  const timer = setInterval(pull, intervalMs);
  return () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    emit(null);
  };
}
