const MAX_COUNT = 100_000;
const MAX_STR = 128;
const MAX_SLUG = 64;
const MAX_PLANNING_ARRAY = 128;
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const PLANNING_SOURCE_RE = /^data:tenant:[a-z0-9]+(?:-[a-z0-9]+)*:planning$/;

export type ProvenanceStatus = 'verified' | 'drift' | 'missing' | 'unavailable';
export type KnowledgeStatus = 'source-plan-only';
export type PlanningRelationship = 'portfolio' | 'operating_branch' | 'product_wing';
export type PlanningAuthority = 'planning-only';
export type PlanningStatus = 'planning_not_provisioned';
export type ProjectStatus = 'planning_not_provisioned';
export type FlowStatus = 'proposed_not_approved';
export type DeskId = 'editorial' | 'creative-production' | 'delivery' | 'growth';

export interface BrandKnowledge {
  registeredSources: number;
  admittedSources: number;
  contextFiles: number;
  plannedFiles: number;
  presentFiles: number;
  missingFiles: number;
  rejectedFiles: number;
  researchFiles: number;
  researchVerified: number;
  researchMissing: number;
  researchDrift: number;
  researchRejected: number;
  status: KnowledgeStatus;
  provenanceStatus: ProvenanceStatus;
}

export interface BrandPlanningProject {
  id: string;
  name: string;
  status: ProjectStatus;
}

export interface BrandPlanningFlow {
  id: string;
  status: FlowStatus;
}

export interface BrandPlanning {
  parent: string | null;
  relationship: PlanningRelationship;
  authority: PlanningAuthority;
  status: PlanningStatus;
  projects: BrandPlanningProject[];
  desks: DeskId[];
  flows: BrandPlanningFlow[];
  sources: string[];
}

export interface BrandPassportInput {
  knowledge?: BrandKnowledge;
  planning?: BrandPlanning;
}

function fail(message: string): never {
  throw new Error(message);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readBoundedCount(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > MAX_COUNT) {
    fail(`Invalid ${field}: expected integer 0..${MAX_COUNT}`);
  }
  return value;
}

function readBoundedString(value: unknown, field: string, max = MAX_STR, allowEmpty = false): string {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0) || value.length > max) {
    fail(`Invalid ${field}: expected string up to ${max} characters`);
  }
  return value;
}

function readSlug(value: unknown, field: string, nullable = false, max = MAX_SLUG): string | null {
  if (value === null) {
    if (!nullable) fail(`Invalid ${field}: slug required`);
    return null;
  }
  if (typeof value !== 'string' || value.length === 0 || value.length > max) {
    fail(`Invalid ${field}: expected slug string up to ${max} characters`);
  }
  if (!SLUG_RE.test(value)) fail(`Invalid ${field}: malformed slug`);
  return value;
}

function readEnum<T extends string>(value: unknown, field: string, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    fail(`Invalid ${field}: expected one of ${allowed.join(', ')}`);
  }
  return value as T;
}

const KNOWLEDGE_COUNT_KEYS = [
  'registeredSources',
  'admittedSources',
  'contextFiles',
  'plannedFiles',
  'presentFiles',
  'missingFiles',
  'rejectedFiles',
  'researchFiles',
  'researchVerified',
  'researchMissing',
  'researchDrift',
  'researchRejected',
] as const;

const KNOWLEDGE_KEYS = new Set<string>([
  ...KNOWLEDGE_COUNT_KEYS,
  'status',
  'provenanceStatus',
]);

const PLANNING_KEYS = new Set<string>([
  'parent',
  'relationship',
  'authority',
  'status',
  'projects',
  'desks',
  'flows',
  'sources',
]);

function assertOnlyKeys(obj: Record<string, unknown>, allowed: Set<string>, label: string): void {
  for (const key of Object.keys(obj)) {
    if (!allowed.has(key)) fail(`Invalid ${label}: unexpected key "${key}"`);
  }
}

function parseKnowledge(raw: unknown): BrandKnowledge {
  if (!isRecord(raw)) fail('Invalid knowledge: expected object');
  assertOnlyKeys(raw, KNOWLEDGE_KEYS, 'knowledge');
  const counts = {} as Record<(typeof KNOWLEDGE_COUNT_KEYS)[number], number>;
  for (const key of KNOWLEDGE_COUNT_KEYS) {
    if (!(key in raw)) fail(`Invalid knowledge: missing ${key}`);
    counts[key] = readBoundedCount(raw[key], `knowledge.${key}`);
  }
  if (!('status' in raw)) fail('Invalid knowledge: missing status');
  if (!('provenanceStatus' in raw)) fail('Invalid knowledge: missing provenanceStatus');
  const status = readEnum(raw.status, 'knowledge.status', ['source-plan-only'] as const);
  const provenanceStatus = readEnum(raw.provenanceStatus, 'knowledge.provenanceStatus', [
    'verified',
    'drift',
    'missing',
    'unavailable',
  ] as const);
  return { ...counts, status, provenanceStatus };
}

function parsePlanning(raw: unknown): BrandPlanning {
  if (!isRecord(raw)) fail('Invalid planning: expected object');
  assertOnlyKeys(raw, PLANNING_KEYS, 'planning');
  if (!('parent' in raw)) fail('Invalid planning: missing parent');
  if (!('relationship' in raw)) fail('Invalid planning: missing relationship');
  if (!('authority' in raw)) fail('Invalid planning: missing authority');
  if (!('status' in raw)) fail('Invalid planning: missing status');
  if (!('projects' in raw)) fail('Invalid planning: missing projects');
  if (!('desks' in raw)) fail('Invalid planning: missing desks');
  if (!('flows' in raw)) fail('Invalid planning: missing flows');
  if (!('sources' in raw)) fail('Invalid planning: missing sources');

  const parent = readSlug(raw.parent, 'planning.parent', true, MAX_SLUG);
  const relationship = readEnum(raw.relationship, 'planning.relationship', [
    'portfolio',
    'operating_branch',
    'product_wing',
  ] as const);
  const authority = readEnum(raw.authority, 'planning.authority', ['planning-only'] as const);
  const status = readEnum(raw.status, 'planning.status', ['planning_not_provisioned'] as const);

  if (!Array.isArray(raw.projects)) fail('Invalid planning.projects: expected array');
  if (raw.projects.length > MAX_PLANNING_ARRAY) fail(`Invalid planning.projects: maximum ${MAX_PLANNING_ARRAY}`);
  const projects = raw.projects.map((entry, index) => {
    if (!isRecord(entry)) fail(`Invalid planning.projects[${index}]: expected object`);
    assertOnlyKeys(entry, new Set(['id', 'name', 'status']), `planning.projects[${index}]`);
    if (!('id' in entry)) fail(`Invalid planning.projects[${index}]: missing id`);
    if (!('name' in entry)) fail(`Invalid planning.projects[${index}]: missing name`);
    if (!('status' in entry)) fail(`Invalid planning.projects[${index}]: missing status`);
    return {
      id: readSlug(entry.id, `planning.projects[${index}].id`, false, MAX_SLUG) as string,
      name: readBoundedString(entry.name, `planning.projects[${index}].name`, MAX_STR, true),
      status: readEnum(entry.status, `planning.projects[${index}].status`, [
        'planning_not_provisioned',
      ] as const),
    };
  });

  if (!Array.isArray(raw.desks)) fail('Invalid planning.desks: expected array');
  if (raw.desks.length > MAX_PLANNING_ARRAY) fail(`Invalid planning.desks: maximum ${MAX_PLANNING_ARRAY}`);
  const desks = raw.desks.map((entry, index) => {
    return readEnum(entry, `planning.desks[${index}]`, [
      'editorial',
      'creative-production',
      'delivery',
      'growth',
    ] as const);
  });

  if (!Array.isArray(raw.flows)) fail('Invalid planning.flows: expected array');
  if (raw.flows.length > MAX_PLANNING_ARRAY) fail(`Invalid planning.flows: maximum ${MAX_PLANNING_ARRAY}`);
  const flows = raw.flows.map((entry, index) => {
    if (!isRecord(entry)) fail(`Invalid planning.flows[${index}]: expected object`);
    assertOnlyKeys(entry, new Set(['id', 'status']), `planning.flows[${index}]`);
    if (!('id' in entry)) fail(`Invalid planning.flows[${index}]: missing id`);
    if (!('status' in entry)) fail(`Invalid planning.flows[${index}]: missing status`);
    return {
      id: readSlug(entry.id, `planning.flows[${index}].id`, false, MAX_SLUG) as string,
      status: readEnum(entry.status, `planning.flows[${index}].status`, [
        'proposed_not_approved',
      ] as const),
    };
  });

  if (!Array.isArray(raw.sources)) fail('Invalid planning.sources: expected array');
  if (raw.sources.length > MAX_PLANNING_ARRAY) fail(`Invalid planning.sources: maximum ${MAX_PLANNING_ARRAY}`);
  const sources = raw.sources.map((entry, index) => {
    const label = readBoundedString(entry, `planning.sources[${index}]`);
    if (!PLANNING_SOURCE_RE.test(label)) {
      fail(`Invalid planning.sources[${index}]: expected data:tenant:<slug>:planning`);
    }
    return label;
  });

  return { parent, relationship, authority, status, projects, desks, flows, sources };
}

export function parseBrandSummary(raw: Record<string, unknown>): BrandPassportInput {
  if (!isRecord(raw)) fail('Invalid brand summary: expected object');
  const allowed = new Set(['knowledge', 'planning']);
  for (const key of Object.keys(raw)) {
    if (!allowed.has(key)) fail(`Invalid brand summary: unexpected key "${key}"`);
  }
  const result: BrandPassportInput = {};
  if ('knowledge' in raw && raw.knowledge !== undefined) {
    result.knowledge = parseKnowledge(raw.knowledge);
  }
  if ('planning' in raw && raw.planning !== undefined) {
    result.planning = parsePlanning(raw.planning);
  }
  return result;
}

function appendLine(parent: HTMLElement, text: string): void {
  const line = document.createElement('p');
  line.textContent = text;
  parent.appendChild(line);
}

export function renderBrandPassport(t: BrandPassportInput): HTMLElement {
  const section = document.createElement('section');
  section.setAttribute('aria-label', 'Imported brand evidence');

  const heading = document.createElement('h2');
  heading.textContent = 'Imported brand evidence';
  section.appendChild(heading);

  if (t.knowledge) {
    const k = t.knowledge;
    appendLine(section, `Planned files: ${k.plannedFiles}`);
    appendLine(section, `Present files: ${k.presentFiles}`);
    appendLine(section, `Missing files: ${k.missingFiles}`);
    appendLine(section, `Canonical context: ${k.contextFiles} files · Sources: ${k.registeredSources} registered / ${k.admittedSources} admitted`);
    appendLine(section, `Research files: ${k.researchFiles} · Verified: ${k.researchVerified} · Missing: ${k.researchMissing} · Drift: ${k.researchDrift} · Rejected: ${k.researchRejected}`);
    appendLine(section, `Status: source plan not completed ingestion (${k.status})`);
    appendLine(section, `Provenance: ${k.provenanceStatus}`);
  } else {
    appendLine(section, 'Knowledge: unavailable');
  }

  if (t.planning) {
    const p = t.planning;
    appendLine(section, `Planning parent: ${p.parent ?? 'none'}`);
    appendLine(section, `Planning relationship: ${p.relationship}`);
    appendLine(section, `Planning authority: ${p.authority}`);
    appendLine(section, `Planning status: ${p.status}`);
    appendLine(section, `Projects: ${p.projects.length}`);
    for (const project of p.projects) {
      appendLine(section, `Project ${project.id} (${project.name}) — ${project.status}`);
    }
    appendLine(section, `Desks: ${p.desks.join(', ')}`);
    appendLine(section, `Flows: ${p.flows.length}`);
    for (const flow of p.flows) {
      appendLine(section, `Flow ${flow.id} — ${flow.status}`);
    }
    appendLine(section, `Planning sources: ${p.sources.length}`);
  } else {
    appendLine(section, 'Planning: unavailable');
  }

  return section;
}
