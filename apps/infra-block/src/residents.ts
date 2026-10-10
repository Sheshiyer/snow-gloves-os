import type { OpsSnapshot, SafeActivityRecord } from './ops-contracts';

export type ResidentSlug =
  | 'ceo'
  | 'cto'
  | 'chief-of-staff'
  | 'librarian'
  | 'interpreter'
  | 'dispatcher'
  | 'sentinel';

export interface ResidentDefinition {
  slug: ResidentSlug;
  nodeId: string;
  name: string;
  role: string;
  color: string;
  accent: string;
  prop: string;
  station: string;
  greeting: string;
  sources: string[];
  route: string[];
}

export interface ResidentPresence {
  slug: ResidentSlug;
  state: 'active' | 'resting' | 'held' | 'unknown';
  evidence: 'observed' | 'unobserved' | 'demo';
  label: string;
  reason: string;
  recordId: string | null;
  observedAt: string | null;
}

export const RESIDENTS: readonly ResidentDefinition[] = Object.freeze([
  Object.freeze({
    slug: 'ceo',
    nodeId: 'agent-ceo',
    name: 'Chief Executive Agent',
    role: 'Sets strategic intent, priorities, and approves cross-domain risk decisions.',
    color: '#c97858',
    accent: '#283d36',
    prop: 'compass',
    station: 'CEO lookout',
    greeting: 'Bring the priorities; I will help frame the next decision.',
    sources: ['agents/ceo/IDENTITY.md', 'agents/ceo/SOUL.md'],
    route: ['agent-ceo', 'agent-chief-of-staff', 'agent-cto', 'agent-ceo'],
  }),
  Object.freeze({
    slug: 'cto',
    nodeId: 'agent-cto',
    name: 'Chief Technology Agent',
    role: 'Owns architectural choices, connector governance posture, and execution quality bar.',
    color: '#87a4ac',
    accent: '#79513a',
    prop: 'blueprint',
    station: 'CTO workshop',
    greeting: 'Bring the architecture; I will ensure standard execution.',
    sources: ['agents/cto/IDENTITY.md', 'agents/cto/SOUL.md'],
    route: ['agent-cto', 'runtime-adapters', 'connector-gate', 'agent-cto'],
  }),
  Object.freeze({
    slug: 'chief-of-staff',
    nodeId: 'agent-chief-of-staff',
    name: 'Chief of Staff (Skill Orchestrator)',
    role: 'Reduces CEO/CTO load by routing the right skill to the right agent for the right context. Owns the skill graph.',
    color: '#d5b466',
    accent: '#283d36',
    prop: 'route-board',
    station: 'Routing desk',
    greeting: 'State the task; I will assign the right agent and skill graph.',
    sources: ['agents/chief-of-staff/IDENTITY.md', 'agents/chief-of-staff/SOUL.md'],
    route: ['agent-chief-of-staff', 'module-catalog', 'agent-dispatcher', 'agent-chief-of-staff'],
  }),
  Object.freeze({
    slug: 'librarian',
    nodeId: 'agent-librarian',
    name: 'Knowledge Librarian',
    role: 'Owns wiki/document ingestion, chunking, NVIDIA embeddings, and tenant-scoped retrieval.',
    color: '#9bac80',
    accent: '#79513a',
    prop: 'book',
    station: 'Archive',
    greeting: 'Query the records; I will provide the grounded context.',
    sources: ['agents/librarian/IDENTITY.md', 'agents/librarian/SOUL.md'],
    route: ['agent-librarian', 'knowledge-archive', 'agent-interpreter', 'agent-librarian'],
  }),
  Object.freeze({
    slug: 'interpreter',
    nodeId: 'agent-interpreter',
    name: 'Interpretation Engine',
    role: 'Turns raw events + retrieved context into entities, policies, risk, and proposed actions.',
    color: '#c89292',
    accent: '#283d36',
    prop: 'lens',
    station: 'Interpretation studio',
    greeting: 'Feed the raw signals; I will derive structured policy and risk.',
    sources: ['agents/interpreter/IDENTITY.md', 'agents/interpreter/SOUL.md'],
    route: ['agent-interpreter', 'knowledge-archive', 'agent-sentinel', 'agent-interpreter'],
  }),
  Object.freeze({
    slug: 'dispatcher',
    nodeId: 'agent-dispatcher',
    name: 'Orchestration Dispatcher',
    role: 'Bridges Hermes events to Paperclip tasks, agents, and approval gates.',
    color: '#699a92',
    accent: '#79513a',
    prop: 'mailbag',
    station: 'Hermes post',
    greeting: 'Bring the event; I will help route it through the approval gates.',
    sources: ['agents/dispatcher/IDENTITY.md', 'agents/dispatcher/SOUL.md'],
    route: ['agent-dispatcher', 'hermes-bus', 'connector-gate', 'agent-dispatcher'],
  }),
  Object.freeze({
    slug: 'sentinel',
    nodeId: 'agent-sentinel',
    name: 'Audit & Risk Sentinel',
    role: 'Maintains traceability, monitors policy breaches, and runs post-action audits.',
    color: '#d8cfb8',
    accent: '#283d36',
    prop: 'shield',
    station: 'Audit post',
    greeting: 'All actions require audit trails and boundary verification.',
    sources: ['agents/sentinel/IDENTITY.md', 'agents/sentinel/SOUL.md'],
    route: ['agent-sentinel', 'connector-gate', 'agent-ceo', 'agent-sentinel'],
  }),
]);

const ORDERED_SLUGS: readonly ResidentSlug[] = [
  'ceo',
  'cto',
  'chief-of-staff',
  'librarian',
  'interpreter',
  'dispatcher',
  'sentinel',
];

const ACTIVE_STATUSES = new Set([
  'active',
  'running',
  'in_progress',
  'in-progress',
  'started',
  'executing',
]);

const RESTING_STATUSES = new Set([
  'completed',
  'complete',
  'succeeded',
  'success',
  'failed',
  'cancelled',
  'canceled',
  'done',
  'finished',
  'idle',
  'resting',
  'stopped',
]);

const HELD_STATUSES_JOB_EVENT = new Set([
  'approval-required',
  'awaiting-approval',
  'awaiting_approval',
  'held',
]);

const HELD_STATUSES_APPROVAL = new Set([
  'pending',
  'awaiting-approval',
  'awaiting_approval',
  'approval-required',
  'held',
]);

const RESOLVED_APPROVAL_STATUSES = new Set([
  'approved',
  'rejected',
  'cancelled',
  'canceled',
  'denied',
  'dismissed',
]);

function parseSafeTimestamp(raw: string | null | undefined, nowMs: number): number | null {
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  if (trimmed === '') return null;

  let parsedMs: number;
  if (/^\d+(\.\d+)?$/.test(trimmed)) {
    const num = Number(trimmed);
    if (!Number.isFinite(num) || num < 0) return null;
    parsedMs = num < 1e12 ? num * 1000 : num;
  } else {
    const iso = /^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.exec(trimmed);
    if (!iso) return null;
    const year = Number(iso[1]), month = Number(iso[2]), day = Number(iso[3]);
    const calendar = new Date(`${iso[1]}-${iso[2]}-${iso[3]}T00:00:00Z`);
    if (calendar.getUTCFullYear() !== year || calendar.getUTCMonth() + 1 !== month || calendar.getUTCDate() !== day) return null;
    parsedMs = Date.parse(trimmed);
    if (Number.isNaN(parsedMs)) return null;
  }

  if (!Number.isFinite(parsedMs) || parsedMs < 0 || parsedMs > 8640000000000000 || parsedMs > nowMs) {
    return null;
  }
  return parsedMs;
}

type ClassifiedKind = 'terminal' | 'held' | 'active' | 'resolved_approval' | 'unknown';

interface InternalEvaluationRecord {
  id: string;
  groupKey: string;
  agent: ResidentSlug;
  timestampMs: number;
  kind: ClassifiedKind;
  status: string;
}

function classifyRecord(
  rec: SafeActivityRecord,
  sourceCategory: 'events' | 'jobs' | 'approvals',
  nowMs: number,
  expectedTenant: string
): InternalEvaluationRecord | null {
  if (!rec || typeof rec !== 'object') return null;
  if (rec.tenant !== expectedTenant) return null;
  if (!rec.agent) return null;
  if (!ORDERED_SLUGS.includes(rec.agent as ResidentSlug)) return null;

  const agent = rec.agent as ResidentSlug;
  const tsMs = parseSafeTimestamp(rec.timestamp, nowMs);
  if (tsMs === null) return null;

  const id = typeof rec.id === 'string' && rec.id.length > 0 ? rec.id : 'unknown-id';
  const statusNorm = typeof rec.status === 'string' ? rec.status.trim().toLowerCase() : '';
  const groupKey = rec.jobId && rec.jobId.trim().length > 0 ? `job:${rec.jobId.trim()}` : `rec:${id}`;

  let kind: ClassifiedKind = 'unknown';

  if (sourceCategory === 'approvals') {
    if (HELD_STATUSES_APPROVAL.has(statusNorm)) {
      kind = 'held';
    } else if (RESOLVED_APPROVAL_STATUSES.has(statusNorm)) {
      kind = 'resolved_approval';
    } else {
      kind = 'unknown';
    }
  } else {
    if (RESTING_STATUSES.has(statusNorm)) {
      kind = 'terminal';
    } else if (HELD_STATUSES_JOB_EVENT.has(statusNorm)) {
      kind = 'held';
    } else if (ACTIVE_STATUSES.has(statusNorm)) {
      kind = 'active';
    } else {
      kind = 'unknown';
    }
  }

  return {
    id,
    groupKey,
    agent,
    timestampMs: tsMs,
    kind,
    status: statusNorm,
  };
}

function getStatusRank(kind: ClassifiedKind): number {
  switch (kind) {
    case 'terminal':
      return 5;
    case 'resolved_approval':
      return 4;
    case 'held':
      return 3;
    case 'unknown':
      return 2;
    case 'active':
      return 1;
    default:
      return 0;
  }
}

interface GroupEvaluationOutcome {
  agent: ResidentSlug;
  groupKey: string;
  kind: ClassifiedKind;
  timestampMs: number;
  recordId: string;
  status: string;
}

function evaluateAgentGroup(records: InternalEvaluationRecord[]): GroupEvaluationOutcome {
  const sorted = [...records].sort((a, b) => {
    if (b.timestampMs !== a.timestampMs) {
      return b.timestampMs - a.timestampMs;
    }
    const rankA = getStatusRank(a.kind);
    const rankB = getStatusRank(b.kind);
    if (rankB !== rankA) {
      return rankB - rankA;
    }
    return b.id.localeCompare(a.id);
  });

  const winner = sorted[0];
  return {
    agent: winner.agent,
    groupKey: winner.groupKey,
    kind: winner.kind,
    timestampMs: winner.timestampMs,
    recordId: winner.id,
    status: winner.status,
  };
}

export function derivePresence(
  snapshot: OpsSnapshot | null,
  nowMs: number,
  stale = false
): ResidentPresence[] {
  if (!Number.isFinite(nowMs) || nowMs < 0 || nowMs > 8640000000000000 || stale || !snapshot || !snapshot.scope || typeof snapshot.scope.tenant !== 'string' || !snapshot.scope.tenant) {
    return ORDERED_SLUGS.map((slug) => ({
      slug,
      state: 'unknown',
      evidence: 'unobserved',
      label: 'No active evidence',
      reason: stale
        ? 'Snapshot marked stale; presence unverified.'
        : 'No scoped tenant presence evidence available.',
      recordId: null,
      observedAt: null,
    }));
  }

  const tenant = snapshot.scope.tenant;
  if (tenant.trim() === '' || tenant !== tenant.trim()) {
    return ORDERED_SLUGS.map((slug) => ({
      slug,
      state: 'unknown',
      evidence: 'unobserved',
      label: 'No active evidence',
      reason: 'Tenant scope is empty.',
      recordId: null,
      observedAt: null,
    }));
  }

  const rawEvents = (snapshot.activity && snapshot.activity.events) || [];
  const rawJobs = (snapshot.activity && snapshot.activity.jobs) || [];
  const rawApprovals = (snapshot.activity && snapshot.activity.approvals) || [];

  // A scoped terminal job record can revoke walking even when its agent field
  // is absent. It never supplies a resident identity or a resting assignment.
  const terminalJobs = new Map<string, number>();
  for (const record of [...rawEvents, ...rawJobs]) {
    if (record.tenant !== tenant || typeof record.jobId !== 'string' || !record.jobId.trim()) continue;
    if (typeof record.status !== 'string' || !RESTING_STATUSES.has(record.status.trim().toLowerCase())) continue;
    const timestampMs = parseSafeTimestamp(record.timestamp, nowMs);
    if (timestampMs === null) continue;
    const key = `job:${record.jobId.trim()}`;
    terminalJobs.set(key, Math.max(terminalJobs.get(key) ?? -1, timestampMs));
  }

  const parsedRecords: InternalEvaluationRecord[] = [];

  for (const r of rawEvents) {
    const parsed = classifyRecord(r, 'events', nowMs, tenant);
    if (parsed) parsedRecords.push(parsed);
  }
  for (const r of rawJobs) {
    const parsed = classifyRecord(r, 'jobs', nowMs, tenant);
    if (parsed) parsedRecords.push(parsed);
  }
  for (const r of rawApprovals) {
    const parsed = classifyRecord(r, 'approvals', nowMs, tenant);
    if (parsed) parsedRecords.push(parsed);
  }

  const agentGroups = new Map<ResidentSlug, Map<string, InternalEvaluationRecord[]>>();
  for (const slug of ORDERED_SLUGS) {
    agentGroups.set(slug, new Map());
  }

  for (const rec of parsedRecords) {
    const groups = agentGroups.get(rec.agent);
    if (groups) {
      const existing = groups.get(rec.groupKey) || [];
      existing.push(rec);
      groups.set(rec.groupKey, existing);
    }
  }

  return ORDERED_SLUGS.map((slug) => {
    const groups = agentGroups.get(slug)!;
    const groupOutcomes: GroupEvaluationOutcome[] = [];

    for (const recList of groups.values()) {
      if (recList.length > 0) {
        const outcome = evaluateAgentGroup(recList);
        if ((outcome.kind === 'active' || outcome.kind === 'held') &&
            (terminalJobs.get(outcome.groupKey) ?? -1) >= outcome.timestampMs) {
          outcome.kind = 'unknown';
        }
        groupOutcomes.push(outcome);
      }
    }

    if (groupOutcomes.length === 0) {
      return {
        slug,
        state: 'unknown',
        evidence: 'unobserved',
        label: 'No active evidence',
        reason: 'No scoped activity records observed for resident.',
        recordId: null,
        observedAt: null,
      };
    }

    const activeOutcomes = groupOutcomes.filter(
      (g) => g.kind === 'active' && nowMs - g.timestampMs <= 120000
    );

    if (activeOutcomes.length > 0) {
      activeOutcomes.sort((a, b) => {
        if (b.timestampMs !== a.timestampMs) return b.timestampMs - a.timestampMs;
        return b.recordId.localeCompare(a.recordId);
      });
      const topActive = activeOutcomes[0];
      return {
        slug,
        state: 'active',
        evidence: 'observed',
        label: 'Active',
        reason: `Active work observed from record status [${topActive.status}].`,
        recordId: topActive.recordId,
        observedAt: new Date(topActive.timestampMs).toISOString(),
      };
    }

    const heldOutcomes = groupOutcomes.filter((g) => g.kind === 'held');
    if (heldOutcomes.length > 0) {
      heldOutcomes.sort((a, b) => {
        if (b.timestampMs !== a.timestampMs) return b.timestampMs - a.timestampMs;
        return b.recordId.localeCompare(a.recordId);
      });
      const topHeld = heldOutcomes[0];
      return {
        slug,
        state: 'held',
        evidence: 'observed',
        label: 'Approval held',
        reason: `Approval hold unresolved from record status [${topHeld.status}].`,
        recordId: topHeld.recordId,
        observedAt: new Date(topHeld.timestampMs).toISOString(),
      };
    }

    const restingOutcomes = groupOutcomes.filter((g) => g.kind === 'terminal');
    if (restingOutcomes.length > 0) {
      restingOutcomes.sort((a, b) => {
        if (b.timestampMs !== a.timestampMs) return b.timestampMs - a.timestampMs;
        return b.recordId.localeCompare(a.recordId);
      });
      const topResting = restingOutcomes[0];
      return {
        slug,
        state: 'resting',
        evidence: 'observed',
        label: 'Resting',
        reason: `Terminal status [${topResting.status}] observed.`,
        recordId: topResting.recordId,
        observedAt: new Date(topResting.timestampMs).toISOString(),
      };
    }

    const oldActiveOutcomes = groupOutcomes.filter((g) => g.kind === 'active');
    if (oldActiveOutcomes.length > 0) {
      return {
        slug,
        state: 'unknown',
        evidence: 'unobserved',
        label: 'No recent active evidence',
        reason: 'Active record exceeded 120000ms threshold.',
        recordId: null,
        observedAt: null,
      };
    }

    return {
      slug,
      state: 'unknown',
      evidence: 'unobserved',
      label: 'No active evidence',
      reason: 'No conclusive active, held, or terminal state derived.',
      recordId: null,
      observedAt: null,
    };
  });
}

export function demoPresence(activeSlug?: ResidentSlug): ResidentPresence[] {
  const isValidSlug = activeSlug !== undefined && ORDERED_SLUGS.includes(activeSlug);

  return ORDERED_SLUGS.map((slug) => {
    if (isValidSlug && slug === activeSlug) {
      return {
        slug,
        state: 'active',
        evidence: 'demo',
        label: 'Demo walking',
        reason: 'Illustrative town mode; active walking demonstration.',
        recordId: null,
        observedAt: null,
      };
    }
    return {
      slug,
      state: 'resting',
      evidence: 'demo',
      label: 'Demo resting',
      reason: 'Illustrative town mode; not infrastructure activity.',
      recordId: null,
      observedAt: null,
    };
  });
}
