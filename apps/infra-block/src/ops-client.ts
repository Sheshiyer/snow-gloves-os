import { parseBrandSummary } from './brand-summary';
import { FLEET_LAYOUT } from './fleet-model';
import type {
  CurrentCatalogAdapter,
  CurrentCatalogAgent,
  CurrentCatalogCard,
  CurrentCatalogConnector,
  OpsDocument,
  OpsSnapshot,
  OpsSnapshotAcceptanceItem,
  OpsSnapshotDocumentItem,
  OpsSnapshotFleetItem,
  OpsSnapshotFleetNode,
  OpsSnapshotRoutingRule,
  OpsSnapshotServiceItem,
  OpsSnapshotTenant,
  OpsSnapshotWarningItem,
  PlanPreview,
  PlanPreviewModule,
  PlanPreviewRoute,
  PlanPreviewStep,
  PlanRequest,
  RequestOptions,
  SafeActivityRecord,
} from './ops-contracts';

export class OpsClientError extends Error {
  readonly code: string;
  readonly status?: number;

  constructor(message: string, code: string, status?: number) {
    super(message);
    this.name = 'OpsClientError';
    this.code = code;
    this.status = status;
    Object.setPrototypeOf(this, OpsClientError.prototype);
  }
}

const FORBIDDEN_KEYS = new Set(['__proto__', 'prototype', 'constructor']);
const ISO_DATE_REGEX = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const SHA256_HEX_REGEX = /^[0-9a-fA-F]{64}$/;
const TENANT_REGEX = /^[_a-z0-9][_a-z0-9-]{0,63}$/;
const MODULE_ID_REGEX = /^[_a-zA-Z0-9][_a-zA-Z0-9-]{0,127}$/;

function isRecord(val: unknown): val is Record<string, unknown> {
  return typeof val === 'object' && val !== null && !Array.isArray(val)
    && (Object.getPrototypeOf(val) === Object.prototype || Object.getPrototypeOf(val) === null);
}

function isISODate(val: unknown): val is string {
  if (typeof val !== 'string' || !ISO_DATE_REGEX.test(val)) return false;
  const timestamp = Date.parse(val);
  return !Number.isNaN(timestamp);
}

function isNonNegativeInteger(val: unknown): val is number {
  return typeof val === 'number' && Number.isSafeInteger(val) && val >= 0;
}

function sanitizeSafeRecord(
  input: unknown,
  maxDepth = 12,
  maxCount = 2000,
  currentDepth = 0,
  nodeCounter: { count: number } = { count: 0 }
): Record<string, unknown> {
  if (currentDepth > maxDepth) {
    throw new OpsClientError('Safe record exceeded maximum nesting depth', 'invalid-response');
  }
  if (!isRecord(input)) {
    throw new OpsClientError('Safe record must be an object', 'invalid-response');
  }

  const result: Record<string, unknown> = {};
  const entries = Object.entries(input);

  for (const [key, value] of entries) {
    if (FORBIDDEN_KEYS.has(key)) {
      throw new OpsClientError(`Safe record contains forbidden key: ${key}`, 'invalid-response');
    }
    nodeCounter.count += 1;
    if (nodeCounter.count > maxCount) {
      throw new OpsClientError('Safe record exceeded maximum node count', 'invalid-response');
    }

    if (value === null) {
      result[key] = null;
    } else if (typeof value === 'string' || typeof value === 'boolean') {
      result[key] = value;
    } else if (typeof value === 'number') {
      if (!Number.isFinite(value)) {
        throw new OpsClientError('Non-finite number in safe record', 'invalid-response');
      }
      result[key] = value;
    } else if (Array.isArray(value)) {
      result[key] = sanitizeSafeArray(value, maxDepth, maxCount, currentDepth + 1, nodeCounter);
    } else if (isRecord(value)) {
      result[key] = sanitizeSafeRecord(value, maxDepth, maxCount, currentDepth + 1, nodeCounter);
    } else {
      throw new OpsClientError('Invalid JSON value in safe record', 'invalid-response');
    }
  }

  return result;
}

function sanitizeSafeArray(
  input: unknown[],
  maxDepth: number,
  maxCount: number,
  currentDepth: number,
  nodeCounter: { count: number }
): unknown[] {
  if (currentDepth > maxDepth) {
    throw new OpsClientError('Safe array exceeded maximum nesting depth', 'invalid-response');
  }
  const result: unknown[] = [];
  for (const item of input) {
    nodeCounter.count += 1;
    if (nodeCounter.count > maxCount) {
      throw new OpsClientError('Safe array exceeded maximum node count', 'invalid-response');
    }
    if (item === null) {
      result.push(null);
    } else if (typeof item === 'string' || typeof item === 'boolean') {
      result.push(item);
    } else if (typeof item === 'number') {
      if (!Number.isFinite(item)) {
        throw new OpsClientError('Non-finite number in safe array', 'invalid-response');
      }
      result.push(item);
    } else if (Array.isArray(item)) {
      result.push(sanitizeSafeArray(item, maxDepth, maxCount, currentDepth + 1, nodeCounter));
    } else if (isRecord(item)) {
      result.push(sanitizeSafeRecord(item, maxDepth, maxCount, currentDepth + 1, nodeCounter));
    } else {
      throw new OpsClientError('Invalid JSON value in safe array', 'invalid-response');
    }
  }
  return result;
}

function parseStringArray(val: unknown, fieldName: string): string[] {
  if (!Array.isArray(val)) {
    throw new OpsClientError(`Field ${fieldName} must be an array of strings`, 'invalid-response');
  }
  for (const item of val) {
    if (typeof item !== 'string') {
      throw new OpsClientError(`Item in ${fieldName} must be a string`, 'invalid-response');
    }
  }
  return [...val];
}

function parseNullableString(val: unknown, fieldName: string): string | null {
  if (val === null || val === undefined) return null;
  if (typeof val === 'string') return val;
  throw new OpsClientError(`Field ${fieldName} must be string or null`, 'invalid-response');
}

function parseActivityRecord(item: unknown, index: number, listName: string): SafeActivityRecord {
  if (!isRecord(item)) {
    throw new OpsClientError(`Activity item in ${listName}[${index}] must be an object`, 'invalid-response');
  }
  if (typeof item.id !== 'string' || item.id.length === 0) {
    throw new OpsClientError(`Activity item id in ${listName}[${index}] is invalid`, 'invalid-response');
  }
  if (typeof item.kind !== 'string' || typeof item.status !== 'string' || typeof item.summary !== 'string') {
    throw new OpsClientError(`Activity item string fields invalid in ${listName}[${index}]`, 'invalid-response');
  }

  const timestamp = parseNullableString(item.timestamp, `${listName}[${index}].timestamp`);
  if (timestamp !== null && !isISODate(timestamp)) {
    throw new OpsClientError(`Activity timestamp in ${listName}[${index}] is not valid ISO`, 'invalid-response');
  }

  const record: SafeActivityRecord = {
    id: item.id,
    timestamp,
    tenant: parseNullableString(item.tenant, `${listName}[${index}].tenant`),
    agent: parseNullableString(item.agent, `${listName}[${index}].agent`),
    kind: item.kind,
    status: item.status,
    jobId: parseNullableString(item.jobId, `${listName}[${index}].jobId`),
    artifactId: parseNullableString(item.artifactId, `${listName}[${index}].artifactId`),
    summary: item.summary,
    nodeId: parseNullableString(item.nodeId, `${listName}[${index}].nodeId`),
  };

  if (record.nodeId !== null && !FLEET_LAYOUT.some(node => node.id === record.nodeId)) {
    throw new OpsClientError(`Activity nodeId in ${listName}[${index}] is not a canonical fleet slot`, 'invalid-response');
  }

  if (item.sources !== undefined && item.sources !== null) {
    record.sources = parseStringArray(item.sources, `${listName}[${index}].sources`);
  }

  return record;
}

function parseFleetNodes(value: unknown, mode: OpsSnapshot['scope']['mode']): OpsSnapshotFleetNode[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length !== FLEET_LAYOUT.length) {
    throw new OpsClientError('Fleet nodes must contain exactly four canonical slots', 'invalid-response');
  }
  const seen = new Set<string>();
  const nodes = value.map((raw, index): OpsSnapshotFleetNode => {
    if (!isRecord(raw)) throw new OpsClientError(`Fleet node [${index}] must be object`, 'invalid-response');
    const slot = FLEET_LAYOUT.find(node => node.id === raw.id);
    if (!slot || seen.has(slot.id) || raw.name !== slot.name || raw.wing !== slot.wing || raw.profileId !== slot.profileId) {
      throw new OpsClientError(`Fleet node identity invalid at ${index}`, 'invalid-response');
    }
    seen.add(slot.id);
    if (raw.assignment !== 'configured' && raw.assignment !== 'planned' && raw.assignment !== 'template') {
      throw new OpsClientError(`Fleet node assignment invalid at ${index}`, 'invalid-response');
    }
    const expectedEvidence = raw.assignment === 'configured' ? 'local' : raw.assignment === 'template' ? 'source' : 'pending';
    if (raw.evidence !== expectedEvidence || (mode === 'public-fixtures' && raw.assignment !== 'template') || (mode === 'local-private' && raw.assignment === 'template')) {
      throw new OpsClientError(`Fleet node evidence or scope invalid at ${index}`, 'invalid-response');
    }
    if (!Array.isArray(raw.sources) || raw.sources.length > 4) {
      throw new OpsClientError(`Fleet node sources invalid at ${index}`, 'invalid-response');
    }
    const islandProfile = `nodes/islands/${slot.id}/node.yaml`;
    const allowedSources = new Set(['catalog/fleet-topology.json', 'fleet.yaml', `nodes/${slot.wing}/node.yaml`, islandProfile]);
    const sources = parseStringArray(raw.sources, `fleetNodes[${index}].sources`);
    if (sources.some(source => !allowedSources.has(source)) || (mode === 'public-fixtures' && sources.some(source => source === 'fleet.yaml' || source === islandProfile))) {
      throw new OpsClientError(`Fleet node source is outside the safe document roster at ${index}`, 'invalid-response');
    }
    // The inventory proves configuration only, never a device observation time.
    if (raw.observedAt !== null) {
      throw new OpsClientError(`Fleet node observedAt requires independent device evidence at ${index}`, 'invalid-response');
    }
    return { id: slot.id, name: slot.name, wing: slot.wing, profileId: slot.profileId, assignment: raw.assignment, evidence: expectedEvidence, sources, observedAt: null };
  });
  return FLEET_LAYOUT.map(slot => nodes.find(node => node.id === slot.id)!);
}

function parseCatalogCard(card: unknown, index: number): CurrentCatalogCard {
  if (!isRecord(card)) {
    throw new OpsClientError(`Catalog card [${index}] must be an object`, 'invalid-response');
  }
  const validCategories = new Set(['skills', 'mcp', 'connector', 'plugin', 'playbook']);
  const validDispositions = new Set(['add', 'pointer', 'hold', 'refuse']);
  const validRisks = new Set(['low', 'medium', 'high']);
  const validApprovals = new Set(['yes', 'no']);

  if (typeof card.id !== 'string' || !card.id) throw new OpsClientError(`Card id missing at ${index}`, 'invalid-response');
  if (typeof card.name !== 'string') throw new OpsClientError(`Card name missing at ${index}`, 'invalid-response');
  if (typeof card.category !== 'string' || !validCategories.has(card.category)) {
    throw new OpsClientError(`Card category invalid at ${index}`, 'invalid-response');
  }
  if (typeof card.kind !== 'string') throw new OpsClientError(`Card kind missing at ${index}`, 'invalid-response');
  if (typeof card.disposition !== 'string' || !validDispositions.has(card.disposition)) {
    throw new OpsClientError(`Card disposition invalid at ${index}`, 'invalid-response');
  }
  if (typeof card.repo !== 'string') throw new OpsClientError(`Card repo missing at ${index}`, 'invalid-response');
  if (typeof card.source !== 'string') throw new OpsClientError(`Card source missing at ${index}`, 'invalid-response');
  if (typeof card.risk !== 'string' || !validRisks.has(card.risk)) {
    throw new OpsClientError(`Card risk invalid at ${index}`, 'invalid-response');
  }
  if (typeof card.approval !== 'string' || !validApprovals.has(card.approval)) {
    throw new OpsClientError(`Card approval invalid at ${index}`, 'invalid-response');
  }
  if (typeof card.summary !== 'string') throw new OpsClientError(`Card summary missing at ${index}`, 'invalid-response');

  const agents = parseStringArray(card.agents, `catalog.cards[${index}].agents`);
  const runtimes = parseStringArray(card.runtimes, `catalog.cards[${index}].runtimes`);

  const out: CurrentCatalogCard = {
    id: card.id,
    name: card.name,
    category: card.category as CurrentCatalogCard['category'],
    kind: card.kind,
    disposition: card.disposition as CurrentCatalogCard['disposition'],
    repo: card.repo,
    source: card.source,
    risk: card.risk as CurrentCatalogCard['risk'],
    approval: card.approval as CurrentCatalogCard['approval'],
    agents,
    runtimes,
    summary: card.summary,
  };

  if (card.hooks !== undefined && card.hooks !== null) {
    out.hooks = parseStringArray(card.hooks, `catalog.cards[${index}].hooks`);
  }
  if (card.enableable !== undefined && card.enableable !== null) {
    if (typeof card.enableable !== 'boolean') {
      throw new OpsClientError(`Card enableable must be boolean at ${index}`, 'invalid-response');
    }
    out.enableable = card.enableable;
  }
  if (card.body !== undefined && card.body !== null) {
    if (typeof card.body !== 'string') {
      throw new OpsClientError(`Card body must be string at ${index}`, 'invalid-response');
    }
    out.body = card.body;
  }
  if (card.mcp !== undefined && card.mcp !== null) {
    if (!isRecord(card.mcp)) {
      throw new OpsClientError(`Card mcp must be object at ${index}`, 'invalid-response');
    }
    const mcpObj: CurrentCatalogCard['mcp'] = {};
    if (card.mcp.command !== undefined && card.mcp.command !== null) {
      if (typeof card.mcp.command !== 'string') throw new OpsClientError(`mcp.command invalid at ${index}`, 'invalid-response');
      mcpObj.command = card.mcp.command;
    }
    if (card.mcp.args !== undefined && card.mcp.args !== null) {
      mcpObj.args = parseStringArray(card.mcp.args, `catalog.cards[${index}].mcp.args`);
    }
    if (card.mcp.url !== undefined && card.mcp.url !== null) {
      if (typeof card.mcp.url !== 'string') throw new OpsClientError(`mcp.url invalid at ${index}`, 'invalid-response');
      mcpObj.url = card.mcp.url;
    }
    if (card.mcp.env !== undefined && card.mcp.env !== null) {
      if (!isRecord(card.mcp.env)) throw new OpsClientError(`mcp.env invalid at ${index}`, 'invalid-response');
      const envOut: Record<string, string> = {};
      for (const [k, v] of Object.entries(card.mcp.env)) {
        if (FORBIDDEN_KEYS.has(k)) throw new OpsClientError(`Forbidden key in mcp.env: ${k}`, 'invalid-response');
        if (typeof v !== 'string') throw new OpsClientError(`mcp.env[${k}] must be string`, 'invalid-response');
        envOut[k] = v;
      }
      mcpObj.env = envOut;
    }
    out.mcp = mcpObj;
  }

  return out;
}

function parseCatalogAgent(agent: unknown, index: number): CurrentCatalogAgent {
  if (!isRecord(agent)) {
    throw new OpsClientError(`Catalog agent [${index}] must be an object`, 'invalid-response');
  }
  if (typeof agent.slug !== 'string' || !agent.slug) throw new OpsClientError(`Agent slug missing at ${index}`, 'invalid-response');
  if (typeof agent.role !== 'string') throw new OpsClientError(`Agent role missing at ${index}`, 'invalid-response');
  if (typeof agent.layer !== 'string') throw new OpsClientError(`Agent layer missing at ${index}`, 'invalid-response');
  if (!isNonNegativeInteger(agent.skill_count)) {
    throw new OpsClientError(`Agent skill_count invalid at ${index}`, 'invalid-response');
  }
  const hooks = parseStringArray(agent.hooks, `catalog.agents[${index}].hooks`);

  return {
    slug: agent.slug,
    role: agent.role,
    layer: agent.layer,
    skill_count: agent.skill_count,
    hooks,
  };
}

function parseCatalogAdapter(adapter: unknown, index: number): CurrentCatalogAdapter {
  if (!isRecord(adapter)) {
    throw new OpsClientError(`Catalog adapter [${index}] must be an object`, 'invalid-response');
  }
  if (adapter.schema !== 'snowgloves.adapter.v1') {
    throw new OpsClientError(`Adapter schema mismatch at ${index}`, 'invalid-response');
  }
  if (typeof adapter.id !== 'string' || !adapter.id) throw new OpsClientError(`Adapter id invalid at ${index}`, 'invalid-response');
  if (typeof adapter.name !== 'string') throw new OpsClientError(`Adapter name invalid at ${index}`, 'invalid-response');
  if (typeof adapter.question_tool !== 'string') throw new OpsClientError(`Adapter question_tool invalid at ${index}`, 'invalid-response');
  if (typeof adapter.notes !== 'string') throw new OpsClientError(`Adapter notes invalid at ${index}`, 'invalid-response');

  const homepage = parseNullableString(adapter.homepage, `catalog.adapters[${index}].homepage`);
  const plan_mode = parseNullableString(adapter.plan_mode, `catalog.adapters[${index}].plan_mode`);
  const plugin_install = parseNullableString(adapter.plugin_install, `catalog.adapters[${index}].plugin_install`);

  if (!isRecord(adapter.paths)) {
    throw new OpsClientError(`Adapter paths invalid at ${index}`, 'invalid-response');
  }
  const paths: Record<string, string | null> = {};
  for (const [k, v] of Object.entries(adapter.paths)) {
    if (FORBIDDEN_KEYS.has(k)) throw new OpsClientError(`Forbidden key in paths: ${k}`, 'invalid-response');
    paths[k] = parseNullableString(v, `catalog.adapters[${index}].paths.${k}`);
  }

  if (!isRecord(adapter.formats)) {
    throw new OpsClientError(`Adapter formats invalid at ${index}`, 'invalid-response');
  }
  const formats: Record<string, string> = {};
  for (const [k, v] of Object.entries(adapter.formats)) {
    if (FORBIDDEN_KEYS.has(k)) throw new OpsClientError(`Forbidden key in formats: ${k}`, 'invalid-response');
    if (typeof v !== 'string') throw new OpsClientError(`Adapter formats.${k} must be string`, 'invalid-response');
    formats[k] = v;
  }

  const install = parseStringArray(adapter.install, `catalog.adapters[${index}].install`);

  const out: CurrentCatalogAdapter = {
    schema: 'snowgloves.adapter.v1',
    id: adapter.id,
    name: adapter.name,
    homepage,
    question_tool: adapter.question_tool,
    plan_mode,
    paths,
    formats,
    install,
    plugin_install,
    notes: adapter.notes,
  };

  if (adapter.verify !== undefined && adapter.verify !== null) {
    if (adapter.verify === true) {
      out.verify = true;
    } else if (isRecord(adapter.verify)) {
      const verifyMap: Record<string, boolean> = {};
      for (const [vk, vv] of Object.entries(adapter.verify)) {
        if (FORBIDDEN_KEYS.has(vk)) throw new OpsClientError(`Forbidden key in verify: ${vk}`, 'invalid-response');
        if (typeof vv !== 'boolean') throw new OpsClientError(`Adapter verify.${vk} must be boolean`, 'invalid-response');
        verifyMap[vk] = vv;
      }
      out.verify = verifyMap;
    } else {
      throw new OpsClientError(`Adapter verify invalid at ${index}`, 'invalid-response');
    }
  }

  return out;
}

function parseCatalogConnector(connector: unknown, index: number): CurrentCatalogConnector {
  if (!isRecord(connector)) {
    throw new OpsClientError(`Catalog connector [${index}] must be an object`, 'invalid-response');
  }
  if (typeof connector.id !== 'string' || !connector.id) throw new OpsClientError(`Connector id invalid at ${index}`, 'invalid-response');
  if (typeof connector.auth !== 'string') throw new OpsClientError(`Connector auth invalid at ${index}`, 'invalid-response');
  if (connector.note !== undefined && typeof connector.note !== 'string') throw new OpsClientError(`Connector note invalid at ${index}`, 'invalid-response');
  if (!Array.isArray(connector.capabilities)) {
    throw new OpsClientError(`Connector capabilities invalid at ${index}`, 'invalid-response');
  }

  const validRisks = new Set(['low', 'medium', 'high']);
  const validApprovals = new Set(['yes', 'no', 'required']);

  const capabilities: CurrentCatalogConnector['capabilities'] = [];
  for (let cIdx = 0; cIdx < connector.capabilities.length; cIdx += 1) {
    const cap = connector.capabilities[cIdx];
    if (!isRecord(cap)) throw new OpsClientError(`Connector capability at ${cIdx} must be object`, 'invalid-response');
    if (typeof cap.id !== 'string' || !cap.id) throw new OpsClientError(`Capability id invalid at ${cIdx}`, 'invalid-response');
    if (typeof cap.risk !== 'string' || !validRisks.has(cap.risk)) {
      throw new OpsClientError(`Capability risk invalid at ${cIdx}`, 'invalid-response');
    }
    const capOut: CurrentCatalogConnector['capabilities'][number] = {
      id: cap.id,
      risk: cap.risk as 'low' | 'medium' | 'high',
    };
    if (cap.approval !== undefined && cap.approval !== null) {
      if (typeof cap.approval !== 'string' || !validApprovals.has(cap.approval)) {
        throw new OpsClientError(`Capability approval invalid at ${cIdx}`, 'invalid-response');
      }
      capOut.approval = cap.approval as 'yes' | 'no' | 'required';
    }
    capabilities.push(capOut);
  }

  const out: CurrentCatalogConnector = {
    id: connector.id,
    auth: connector.auth,
    capabilities,
    ...(typeof connector.note === 'string' ? {note: connector.note} : {}),
  };

  if (connector.base_url !== undefined && connector.base_url !== null) {
    if (typeof connector.base_url !== 'string') throw new OpsClientError(`Connector base_url invalid at ${index}`, 'invalid-response');
    out.base_url = connector.base_url;
  }

  return out;
}

export function validateSnapshot(unknownData: unknown): OpsSnapshot {
  if (!isRecord(unknownData)) {
    throw new OpsClientError('Snapshot payload must be an object', 'invalid-response');
  }

  if (unknownData.schema !== 'snowgloves.cockpit.v1') {
    throw new OpsClientError('Invalid snapshot schema version', 'invalid-response');
  }

  if (!isISODate(unknownData.generatedAt)) {
    throw new OpsClientError('Invalid snapshot generatedAt timestamp', 'invalid-response');
  }

  if (!isRecord(unknownData.scope)) {
    throw new OpsClientError('Missing snapshot scope', 'invalid-response');
  }
  const mode = unknownData.scope.mode;
  if (mode !== 'public-fixtures' && mode !== 'local-private') {
    throw new OpsClientError('Invalid snapshot scope mode', 'invalid-response');
  }
  const scopeTenant = parseNullableString(unknownData.scope.tenant, 'scope.tenant');
  if (unknownData.scope.readOnly !== true) {
    throw new OpsClientError('Snapshot scope readOnly must be strictly true', 'invalid-response');
  }

  if (!isRecord(unknownData.capabilities)) {
    throw new OpsClientError('Missing snapshot capabilities', 'invalid-response');
  }
  if (
    unknownData.capabilities.documents !== true ||
    unknownData.capabilities.planPreview !== true ||
    unknownData.capabilities.execute !== false ||
    unknownData.capabilities.enable !== false ||
    unknownData.capabilities.approve !== false
  ) {
    throw new OpsClientError('Invalid or unsafe capabilities configuration', 'invalid-response');
  }

  if (!isRecord(unknownData.catalog)) {
    throw new OpsClientError('Missing snapshot catalog', 'invalid-response');
  }
  if (
    !Array.isArray(unknownData.catalog.cards) ||
    !Array.isArray(unknownData.catalog.agents) ||
    !Array.isArray(unknownData.catalog.adapters) ||
    !Array.isArray(unknownData.catalog.connectors)
  ) {
    throw new OpsClientError('Catalog collections must be arrays', 'invalid-response');
  }

  const cards = unknownData.catalog.cards.map((c, i) => parseCatalogCard(c, i));
  const agents = unknownData.catalog.agents.map((a, i) => parseCatalogAgent(a, i));
  const adapters = unknownData.catalog.adapters.map((ad, i) => parseCatalogAdapter(ad, i));
  const connectors = unknownData.catalog.connectors.map((cn, i) => parseCatalogConnector(cn, i));

  if (!Array.isArray(unknownData.tenants)) {
    throw new OpsClientError('Tenants must be an array', 'invalid-response');
  }
  const tenants: OpsSnapshotTenant[] = unknownData.tenants.map((t, idx) => {
    if (!isRecord(t)) throw new OpsClientError(`Tenant [${idx}] must be object`, 'invalid-response');
    if (typeof t.slug !== 'string' || !t.slug) throw new OpsClientError(`Tenant slug invalid at ${idx}`, 'invalid-response');
    if (typeof t.name !== 'string') throw new OpsClientError(`Tenant name invalid at ${idx}`, 'invalid-response');
    const primaryRuntime = parseNullableString(t.primaryRuntime, `tenants[${idx}].primaryRuntime`);
    const tenantAgents = parseStringArray(t.agents, `tenants[${idx}].agents`);
    const enabledModules = parseStringArray(t.enabledModules, `tenants[${idx}].enabledModules`);
    if (!isRecord(t.approvalCounts)) throw new OpsClientError(`Tenant approvalCounts invalid at ${idx}`, 'invalid-response');
    if (
      !isNonNegativeInteger(t.approvalCounts.pending) ||
      !isNonNegativeInteger(t.approvalCounts.approved) ||
      !isNonNegativeInteger(t.approvalCounts.rejected)
    ) {
      throw new OpsClientError(`Tenant approvalCounts non-negative int violation at ${idx}`, 'invalid-response');
    }
    if (!isNonNegativeInteger(t.sourceCount)) {
      throw new OpsClientError(`Tenant sourceCount must be non-negative integer at ${idx}`, 'invalid-response');
    }
    const sources = parseStringArray(t.sources, `tenants[${idx}].sources`);
    if (t.availability !== 'fixture' && t.availability !== 'local') {
      throw new OpsClientError(`Tenant availability invalid at ${idx}`, 'invalid-response');
    }
    const warnings = parseStringArray(t.warnings, `tenants[${idx}].warnings`);
    let brandSummary;
    try { brandSummary = parseBrandSummary({knowledge:t.knowledge, planning:t.planning}); }
    catch { throw new OpsClientError(`Invalid tenant brand summary at ${idx}`, 'invalid-response'); }

    return {
      ...brandSummary,
      slug: t.slug,
      name: t.name,
      primaryRuntime,
      agents: tenantAgents,
      enabledModules,
      approvalCounts: {
        pending: t.approvalCounts.pending,
        approved: t.approvalCounts.approved,
        rejected: t.approvalCounts.rejected,
      },
      sourceCount: t.sourceCount,
      sources,
      availability: t.availability,
      warnings,
    };
  });

  if (!Array.isArray(unknownData.fleet)) {
    throw new OpsClientError('Fleet must be an array', 'invalid-response');
  }
  const fleet: OpsSnapshotFleetItem[] = unknownData.fleet.map((f, idx) => {
    if (!isRecord(f)) throw new OpsClientError(`Fleet item [${idx}] must be object`, 'invalid-response');
    if (typeof f.id !== 'string' || !f.id) throw new OpsClientError(`Fleet id invalid at ${idx}`, 'invalid-response');
    if (typeof f.name !== 'string') throw new OpsClientError(`Fleet name invalid at ${idx}`, 'invalid-response');
    if (typeof f.wing !== 'string') throw new OpsClientError(`Fleet wing invalid at ${idx}`, 'invalid-response');
    const runtime = parseNullableString(f.runtime, `fleet[${idx}].runtime`);
    const profile = sanitizeSafeRecord(f.profile);
    const sources = parseStringArray(f.sources, `fleet[${idx}].sources`);
    if (f.evidence !== 'source' && f.evidence !== 'local' && f.evidence !== 'pending') {
      throw new OpsClientError(`Fleet evidence invalid at ${idx}`, 'invalid-response');
    }
    return {
      id: f.id,
      name: f.name,
      wing: f.wing,
      runtime,
      profile,
      sources,
      evidence: f.evidence,
    };
  });
  const fleetNodes = parseFleetNodes(unknownData.fleetNodes, unknownData.scope.mode as OpsSnapshot['scope']['mode']);

  if (!isRecord(unknownData.activity)) {
    throw new OpsClientError('Activity must be an object', 'invalid-response');
  }
  if (
    !Array.isArray(unknownData.activity.events) ||
    !Array.isArray(unknownData.activity.jobs) ||
    !Array.isArray(unknownData.activity.artifacts) ||
    !Array.isArray(unknownData.activity.approvals)
  ) {
    throw new OpsClientError('Activity categories must be arrays', 'invalid-response');
  }
  const activity = {
    events: unknownData.activity.events.map((e, i) => parseActivityRecord(e, i, 'events')),
    jobs: unknownData.activity.jobs.map((j, i) => parseActivityRecord(j, i, 'jobs')),
    artifacts: unknownData.activity.artifacts.map((a, i) => parseActivityRecord(a, i, 'artifacts')),
    approvals: unknownData.activity.approvals.map((ap, i) => parseActivityRecord(ap, i, 'approvals')),
  };

  if (!Array.isArray(unknownData.acceptance)) {
    throw new OpsClientError('Acceptance must be an array', 'invalid-response');
  }
  const acceptance: OpsSnapshotAcceptanceItem[] = unknownData.acceptance.map((acc, idx) => {
    if (!isRecord(acc)) throw new OpsClientError(`Acceptance item [${idx}] must be object`, 'invalid-response');
    if (typeof acc.id !== 'string' || !acc.id) throw new OpsClientError(`Acceptance id invalid at ${idx}`, 'invalid-response');
    if (typeof acc.criterion !== 'string') throw new OpsClientError(`Acceptance criterion invalid at ${idx}`, 'invalid-response');
    if (acc.status !== 'open' && acc.status !== 'accepted') {
      throw new OpsClientError(`Acceptance status invalid at ${idx}`, 'invalid-response');
    }
    if (acc.source !== 'ISA.md') {
      throw new OpsClientError(`Acceptance source must be ISA.md at ${idx}`, 'invalid-response');
    }
    return {
      id: acc.id,
      criterion: acc.criterion,
      status: acc.status,
      source: 'ISA.md',
    };
  });

  if (!isRecord(unknownData.routing)) {
    throw new OpsClientError('Routing must be an object', 'invalid-response');
  }
  if (!Array.isArray(unknownData.routing.rules) || !Array.isArray(unknownData.routing.skills)) {
    throw new OpsClientError('Routing rules and skills must be arrays', 'invalid-response');
  }
  const rules: OpsSnapshotRoutingRule[] = unknownData.routing.rules.map((r, idx) => {
    if (!isRecord(r)) throw new OpsClientError(`Routing rule [${idx}] must be object`, 'invalid-response');
    if (typeof r.id !== 'string' || !r.id) throw new OpsClientError(`Routing rule id invalid at ${idx}`, 'invalid-response');
    if (typeof r.agent !== 'string') throw new OpsClientError(`Routing rule agent invalid at ${idx}`, 'invalid-response');
    if (typeof r.hook !== 'string') throw new OpsClientError(`Routing rule hook invalid at ${idx}`, 'invalid-response');
    if (typeof r.source !== 'string') throw new OpsClientError(`Routing rule source invalid at ${idx}`, 'invalid-response');
    const globs = parseStringArray(r.globs, `routing.rules[${idx}].globs`);
    const skills = parseStringArray(r.skills, `routing.rules[${idx}].skills`);
    return {
      id: r.id,
      agent: r.agent,
      hook: r.hook,
      globs,
      skills,
      source: r.source,
    };
  });
  const routingSkills: Record<string, unknown>[] = unknownData.routing.skills.map((sk) => sanitizeSafeRecord(sk));

  if (!Array.isArray(unknownData.documents)) {
    throw new OpsClientError('Documents must be an array', 'invalid-response');
  }
  const documents: OpsSnapshotDocumentItem[] = unknownData.documents.map((doc, idx) => {
    if (!isRecord(doc)) throw new OpsClientError(`Document [${idx}] must be object`, 'invalid-response');
    if (typeof doc.path !== 'string' || !doc.path) throw new OpsClientError(`Document path invalid at ${idx}`, 'invalid-response');
    if (typeof doc.title !== 'string') throw new OpsClientError(`Document title invalid at ${idx}`, 'invalid-response');
    if (typeof doc.kind !== 'string') throw new OpsClientError(`Document kind invalid at ${idx}`, 'invalid-response');
    if (!isNonNegativeInteger(doc.bytes)) throw new OpsClientError(`Document bytes invalid at ${idx}`, 'invalid-response');
    return {
      path: doc.path,
      title: doc.title,
      kind: doc.kind,
      bytes: doc.bytes,
    };
  });

  if (!Array.isArray(unknownData.services)) {
    throw new OpsClientError('Services must be an array', 'invalid-response');
  }
  const validServiceStates = new Set(['reachable', 'unreachable', 'auth-required', 'unknown']);
  const services: OpsSnapshotServiceItem[] = unknownData.services.map((svc, idx) => {
    if (!isRecord(svc)) throw new OpsClientError(`Service [${idx}] must be object`, 'invalid-response');
    if (typeof svc.id !== 'string' || !svc.id) throw new OpsClientError(`Service id invalid at ${idx}`, 'invalid-response');
    if (typeof svc.label !== 'string') throw new OpsClientError(`Service label invalid at ${idx}`, 'invalid-response');
    if (typeof svc.url !== 'string') throw new OpsClientError(`Service url invalid at ${idx}`, 'invalid-response');
    if (typeof svc.state !== 'string' || !validServiceStates.has(svc.state)) {
      throw new OpsClientError(`Service state invalid at ${idx}`, 'invalid-response');
    }
    if (svc.scope !== 'endpoint-only') {
      throw new OpsClientError(`Service scope must be endpoint-only at ${idx}`, 'invalid-response');
    }
    const checkedAt = parseNullableString(svc.checkedAt, `services[${idx}].checkedAt`);
    if (checkedAt !== null && !isISODate(checkedAt)) {
      throw new OpsClientError(`Service checkedAt must be ISO date at ${idx}`, 'invalid-response');
    }
    let latencyMs: number | null = null;
    if (svc.latencyMs !== undefined && svc.latencyMs !== null) {
      if (typeof svc.latencyMs !== 'number' || !Number.isFinite(svc.latencyMs) || svc.latencyMs < 0) {
        throw new OpsClientError(`Service latencyMs must be finite and non-negative at ${idx}`, 'invalid-response');
      }
      latencyMs = svc.latencyMs;
    }
    return {
      id: svc.id,
      label: svc.label,
      url: svc.url,
      state: svc.state as OpsSnapshotServiceItem['state'],
      checkedAt,
      latencyMs,
      scope: 'endpoint-only',
    };
  });

  if (!Array.isArray(unknownData.warnings)) {
    throw new OpsClientError('Warnings must be an array', 'invalid-response');
  }
  const warnings: OpsSnapshotWarningItem[] = unknownData.warnings.map((w, idx) => {
    if (!isRecord(w)) throw new OpsClientError(`Warning [${idx}] must be object`, 'invalid-response');
    if (typeof w.code !== 'string' || typeof w.message !== 'string') {
      throw new OpsClientError(`Warning item invalid at ${idx}`, 'invalid-response');
    }
    return {
      code: w.code,
      message: w.message,
    };
  });

  return {
    schema: 'snowgloves.cockpit.v1',
    generatedAt: unknownData.generatedAt,
    scope: {
      mode,
      tenant: scopeTenant,
      readOnly: true,
    },
    catalog: {
      cards,
      agents,
      adapters,
      connectors,
    },
    tenants,
    fleet,
    ...(fleetNodes ? { fleetNodes } : {}),
    activity,
    acceptance,
    routing: {
      rules,
      skills: routingSkills,
    },
    documents,
    services,
    warnings,
    capabilities: {
      documents: true,
      planPreview: true,
      execute: false,
      enable: false,
      approve: false,
    },
  };
}

export function validateDocument(unknownData: unknown): OpsDocument {
  if (!isRecord(unknownData)) {
    throw new OpsClientError('Document payload must be an object', 'invalid-response');
  }
  if (typeof unknownData.path !== 'string' || !unknownData.path) {
    throw new OpsClientError('Document path must be non-empty string', 'invalid-response');
  }
  if (typeof unknownData.content !== 'string') {
    throw new OpsClientError('Document content must be string', 'invalid-response');
  }
  if (typeof unknownData.truncated !== 'boolean') {
    throw new OpsClientError('Document truncated must be boolean', 'invalid-response');
  }
  if (typeof unknownData.sha256 !== 'string' || !SHA256_HEX_REGEX.test(unknownData.sha256)) {
    throw new OpsClientError('Document sha256 must be 64-character hex string', 'invalid-response');
  }

  return {
    path: unknownData.path,
    content: unknownData.content,
    truncated: unknownData.truncated,
    sha256: unknownData.sha256.toLowerCase(),
  };
}

export function validatePlanPreview(unknownData: unknown): PlanPreview {
  if (!isRecord(unknownData)) {
    throw new OpsClientError('Plan preview payload must be an object', 'invalid-response');
  }
  if (unknownData.schema !== 'snowgloves.cockpit.plan.v1') {
    throw new OpsClientError('Invalid plan preview schema', 'invalid-response');
  }
  if (typeof unknownData.id !== 'string' || !unknownData.id) {
    throw new OpsClientError('Plan preview id must be non-empty string', 'invalid-response');
  }
  if (typeof unknownData.tenant !== 'string' || !unknownData.tenant) {
    throw new OpsClientError('Plan preview tenant must be non-empty string', 'invalid-response');
  }
  if (typeof unknownData.title !== 'string') {
    throw new OpsClientError('Plan preview title must be string', 'invalid-response');
  }
  if (!isISODate(unknownData.generatedAt)) {
    throw new OpsClientError('Plan preview generatedAt must be ISO date', 'invalid-response');
  }
  if (unknownData.executable !== false) {
    throw new OpsClientError('Plan preview executable flag must be strictly false', 'invalid-response');
  }

  if (!Array.isArray(unknownData.routes)) {
    throw new OpsClientError('Plan preview routes must be an array', 'invalid-response');
  }
  const routes: PlanPreviewRoute[] = unknownData.routes.map((r, idx) => {
    if (!isRecord(r)) throw new OpsClientError(`Route [${idx}] must be object`, 'invalid-response');
    if (typeof r.agent !== 'string' || typeof r.hook !== 'string' || typeof r.source !== 'string') {
      throw new OpsClientError(`Route fields invalid at ${idx}`, 'invalid-response');
    }
    const skills = parseStringArray(r.skills, `routes[${idx}].skills`);
    return {
      agent: r.agent,
      hook: r.hook,
      skills,
      source: r.source,
    };
  });

  if (!Array.isArray(unknownData.modules)) {
    throw new OpsClientError('Plan preview modules must be an array', 'invalid-response');
  }
  const validDecisions = new Set(['allowed', 'approval-required', 'disabled', 'refused', 'unknown']);
  const modules: PlanPreviewModule[] = unknownData.modules.map((m, idx) => {
    if (!isRecord(m)) throw new OpsClientError(`Module [${idx}] must be object`, 'invalid-response');
    if (typeof m.id !== 'string' || !m.id) throw new OpsClientError(`Module id invalid at ${idx}`, 'invalid-response');
    if (typeof m.decision !== 'string' || !validDecisions.has(m.decision)) {
      throw new OpsClientError(`Module decision invalid at ${idx}`, 'invalid-response');
    }
    if (typeof m.reason !== 'string') throw new OpsClientError(`Module reason invalid at ${idx}`, 'invalid-response');
    return {
      id: m.id,
      decision: m.decision as PlanPreviewModule['decision'],
      reason: m.reason,
    };
  });

  if (!Array.isArray(unknownData.steps)) {
    throw new OpsClientError('Plan preview steps must be an array', 'invalid-response');
  }
  const steps: PlanPreviewStep[] = unknownData.steps.map((st, idx) => {
    if (!isRecord(st)) throw new OpsClientError(`Step [${idx}] must be object`, 'invalid-response');
    if (typeof st.id !== 'string' || !st.id) throw new OpsClientError(`Step id invalid at ${idx}`, 'invalid-response');
    if (typeof st.label !== 'string') throw new OpsClientError(`Step label invalid at ${idx}`, 'invalid-response');
    if (st.status !== 'proposed' && st.status !== 'held') {
      throw new OpsClientError(`Step status invalid at ${idx}`, 'invalid-response');
    }
    if (typeof st.reason !== 'string') throw new OpsClientError(`Step reason invalid at ${idx}`, 'invalid-response');
    return {
      id: st.id,
      label: st.label,
      status: st.status,
      reason: st.reason,
    };
  });

  const warnings = parseStringArray(unknownData.warnings, 'planPreview.warnings');

  return {
    schema: 'snowgloves.cockpit.plan.v1',
    id: unknownData.id,
    tenant: unknownData.tenant,
    title: unknownData.title,
    generatedAt: unknownData.generatedAt,
    routes,
    modules,
    steps,
    executable: false,
    warnings,
  };
}

function sanitizeDocumentPath(rawPath: string): string {
  if (typeof rawPath !== 'string' || rawPath.length === 0) {
    throw new OpsClientError('Document path cannot be empty', 'invalid-path');
  }
  if (rawPath.includes('\0')) {
    throw new OpsClientError('Document path contains null bytes', 'invalid-path');
  }
  if (rawPath.includes('\\')) {
    throw new OpsClientError('Document path cannot contain backslashes', 'invalid-path');
  }
  if (rawPath.startsWith('/') || rawPath.startsWith('//')) {
    throw new OpsClientError('Document path cannot be absolute', 'invalid-path');
  }
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(rawPath)) {
    throw new OpsClientError('Document path cannot contain URL schemes', 'invalid-path');
  }

  const segments = rawPath.split('/');
  for (const segment of segments) {
    if (segment === '' || segment === '.' || segment === '..') {
      throw new OpsClientError('Document path cannot contain dot, dot-dot, or empty segments', 'invalid-path');
    }
  }

  return rawPath;
}

function sanitizePlanRequest(request: PlanRequest): PlanRequest {
  if (!isRecord(request)) {
    throw new OpsClientError('Plan request must be an object', 'invalid-request');
  }
  if (typeof request.tenant !== 'string' || !TENANT_REGEX.test(request.tenant)) {
    throw new OpsClientError('Invalid tenant format in plan request', 'invalid-request');
  }
  if (typeof request.title !== 'string') {
    throw new OpsClientError('Plan request title must be string', 'invalid-request');
  }
  const trimmedTitle = request.title.trim();
  if (trimmedTitle.length === 0 || trimmedTitle.length > 2000) {
    throw new OpsClientError('Plan request title must be non-empty and <= 2000 characters', 'invalid-request');
  }

  if (!Array.isArray(request.modules)) {
    throw new OpsClientError('Plan request modules must be an array', 'invalid-request');
  }
  if (request.modules.length > 200) {
    throw new OpsClientError('Plan request modules exceeded maximum count of 200', 'invalid-request');
  }

  const moduleSet = new Set<string>();
  const sanitizedModules: string[] = [];
  for (const mod of request.modules) {
    if (typeof mod !== 'string' || /\s/.test(mod) || !MODULE_ID_REGEX.test(mod)) {
      throw new OpsClientError(`Invalid module ID format: ${String(mod)}`, 'invalid-request');
    }
    if (!moduleSet.has(mod)) {
      moduleSet.add(mod);
      sanitizedModules.push(mod);
    }
  }

  const result: PlanRequest = {
    tenant: request.tenant,
    title: trimmedTitle,
    modules: sanitizedModules,
  };

  if (request.runtime !== undefined && request.runtime !== null) {
    if (typeof request.runtime !== 'string' || request.runtime.trim().length === 0) {
      throw new OpsClientError('Runtime must be a non-empty string when provided', 'invalid-request');
    }
    result.runtime = request.runtime.trim();
  }

  if (request.wing !== undefined && request.wing !== null) {
    if (typeof request.wing !== 'string' || request.wing.trim().length === 0) {
      throw new OpsClientError('Wing must be a non-empty string when provided', 'invalid-request');
    }
    result.wing = request.wing.trim();
  }

  return result;
}

async function executeFetch(
  url: string,
  init: RequestInit,
  options?: RequestOptions
): Promise<unknown> {
  if (options?.timeoutMs !== undefined && !Number.isFinite(options.timeoutMs)) {
    throw new OpsClientError('Invalid request deadline', 'invalid-request');
  }
  const timeoutMs = Math.min(30000, Math.max(1, options?.timeoutMs ?? 8000));
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let externalListener: (() => void) | null = null;
  let timedOut = false;
  let rejectAbort: (reason: OpsClientError) => void = () => {};
  const abortedPromise = new Promise<never>((_, reject) => { rejectAbort = reject; });

  if (options?.signal) {
    if (options.signal.aborted) {
      controller.abort();
      throw new OpsClientError('Request aborted before start', 'aborted');
    }
    externalListener = () => {
      controller.abort();
      rejectAbort(new OpsClientError('Request aborted', 'aborted'));
    };
    options.signal.addEventListener('abort', externalListener);
  }

  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new OpsClientError(`Request timed out after ${timeoutMs}ms`, 'timeout'));
    }, timeoutMs);
  });

  try {
    const fetchPromise = (async () => {
      let response: Response;
      try {
        response = await fetch(url, {
          ...init,
          signal: controller.signal,
          credentials: 'same-origin',
          cache: 'no-store',
        });
      } catch (err: unknown) {
        if (timedOut) {
          throw new OpsClientError(`Request timed out after ${timeoutMs}ms`, 'timeout');
        }
        if (options?.signal?.aborted || (err instanceof Error && err.name === 'AbortError')) {
          throw new OpsClientError('Request aborted', 'aborted');
        }
        throw new OpsClientError(
          'Network request failed',
          'network'
        );
      }

      if (!response.ok) {
        throw new OpsClientError(
          `HTTP request failed with status ${response.status}`,
          'http',
          response.status
        );
      }

      try {
        return await response.json();
      } catch (jsonErr: unknown) {
        if (timedOut) {
          throw new OpsClientError(`Request timed out after ${timeoutMs}ms`, 'timeout');
        }
        if (options?.signal?.aborted || (jsonErr instanceof Error && jsonErr.name === 'AbortError')) {
          throw new OpsClientError('Request aborted', 'aborted');
        }
        throw new OpsClientError('Failed to parse JSON response', 'invalid-response');
      }
    })();

    return await Promise.race([fetchPromise, timeoutPromise, abortedPromise]);
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
    if (options?.signal && externalListener !== null) {
      options.signal.removeEventListener('abort', externalListener);
    }
  }
}

export async function loadSnapshot(tenant?: string, options?: RequestOptions): Promise<OpsSnapshot> {
  if (tenant !== undefined && tenant !== null) {
    if (typeof tenant !== 'string' || !TENANT_REGEX.test(tenant)) {
      throw new OpsClientError('Invalid tenant format for snapshot load', 'invalid-request');
    }
  }

  const url = tenant
    ? `/api/infra/snapshot?tenant=${encodeURIComponent(tenant)}`
    : '/api/infra/snapshot';

  const raw = await executeFetch(
    url,
    {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    },
    options
  );

  const snapshot = validateSnapshot(raw);

  if (tenant !== undefined && tenant !== null) {
    if (snapshot.scope.tenant !== tenant) {
      throw new OpsClientError(
        `Scope tenant mismatch: expected ${tenant}, received ${String(snapshot.scope.tenant)}`,
        'invalid-response'
      );
    }
  }

  return snapshot;
}

export async function loadDocument(rawPath: string, options?: RequestOptions): Promise<OpsDocument> {
  const cleanPath = sanitizeDocumentPath(rawPath);
  const url = `/api/infra/document?path=${encodeURIComponent(cleanPath)}`;

  const raw = await executeFetch(
    url,
    {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    },
    options
  );

  const doc = validateDocument(raw);
  if (doc.path !== cleanPath) {
    throw new OpsClientError(
      `Returned document path does not match requested path: ${doc.path} vs ${cleanPath}`,
      'invalid-response'
    );
  }

  return doc;
}

export async function previewPlan(request: PlanRequest, options?: RequestOptions): Promise<PlanPreview> {
  const canonicalRequest = sanitizePlanRequest(request);

  const raw = await executeFetch(
    '/api/infra/plan',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(canonicalRequest),
    },
    options
  );

  const preview = validatePlanPreview(raw);

  if (preview.tenant !== canonicalRequest.tenant) {
    throw new OpsClientError(
      `Preview tenant mismatch: expected ${canonicalRequest.tenant}, got ${preview.tenant}`,
      'invalid-response'
    );
  }
  if (preview.title !== canonicalRequest.title) {
    throw new OpsClientError(
      `Preview title mismatch: expected ${canonicalRequest.title}, got ${preview.title}`,
      'invalid-response'
    );
  }

  return preview;
}
