/** Configuration evidence only. No field in this contract certifies a live connection. */
export type ConfigState = 'configured' | 'missing' | 'held';
export type ModuleCategory = 'skills' | 'mcp' | 'connector' | 'plugin' | 'playbook' | 'mod' | 'unknown';
export interface ConfiguredModule {
  id: string; name: string; category: ModuleCategory;
  disposition: 'add' | 'pointer' | 'hold' | 'refuse' | 'unknown';
  risk: 'low' | 'medium' | 'high' | 'unknown'; approval: 'yes' | 'no' | 'unknown';
  gate: 'held' | 'approval_required' | 'catalog_permitted'; roles: string[];
}
export interface TenantCapabilityMap {
  tenant: string; status: 'source_config_only'; connectionAuth: 'unverified';
  catalogState: ConfigState; templatesState: ConfigState; enabledState: ConfigState;
  runtimeState: ConfigState; runtime: string | null; sourcesState: ConfigState;
  configuredModules: ConfiguredModule[];
  assignedAgents: {id: string; status: 'configured' | 'held'}[];
  availableControlRoles: {id: string; name: string}[];
  availableBusinessRoles: {id: string; name: string; desk: string; controlOwner: string; preparationOnly: true}[];
  registeredSources: {id: string; type: string; admitted: boolean}[];
}
const CONTROL = ['ceo', 'cto', 'chief-of-staff', 'librarian', 'interpreter', 'dispatcher', 'sentinel'] as const;
const TYPES = ['filesystem', 'obsidian', 'git', 'github', 'google-drive', 'gdrive', 'drive', 'notebooklm', 'url', 'web', 'manual', 'document', 'api', 'email', 'vault'] as const;
const SENSITIVE = /(?:^|[^a-z0-9])(?:secret|password|passwd|credentials?|token|bearer)(?:$|[^a-z0-9])|api[_. -]?key|(?:^|[^a-z0-9])(?:sk-|ghp_|github_pat_)/i;
function fail(): never { throw new Error('Invalid tenant capability map'); }
function record(v: unknown, keys: string[]): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return fail();
  const r = v as Record<string, unknown>;
  if (Object.keys(r).length !== keys.length || keys.some(k => !Object.hasOwn(r, k))) return fail();
  return r;
}
function id(v: unknown): string {
  if (typeof v !== 'string' || /[\r\n]/.test(v) || !/^[a-z0-9_][a-z0-9_.-]{0,63}$/.test(v) || SENSITIVE.test(v)) return fail();
  return v;
}
function name(v: unknown): string {
  if (typeof v !== 'string' || /[\r\n]/.test(v) || v.length < 1 || v.length > 96 || !/^[A-Za-z0-9 &(),.'+/_-]+$/.test(v) || SENSITIVE.test(v)) return fail();
  return v;
}
function one<T extends string>(v: unknown, values: readonly T[]): T {
  if (typeof v !== 'string' || !values.includes(v as T)) return fail();
  return v as T;
}
function list<T>(v: unknown, parse: (item: unknown) => T, max = 128): T[] {
  if (!Array.isArray(v) || v.length > max) return fail();
  return v.map(parse);
}
function unique<T extends {id: string}>(v: T[]): T[] {
  if (new Set(v.map(item => item.id)).size !== v.length) return fail();
  return v;
}
export function parseTenantCapabilityMap(raw: unknown, tenant: string): TenantCapabilityMap {
  const r = record(raw, ['tenant', 'status', 'connectionAuth', 'catalogState', 'templatesState', 'enabledState', 'runtimeState', 'runtime', 'sourcesState', 'configuredModules', 'assignedAgents', 'availableControlRoles', 'availableBusinessRoles', 'registeredSources']);
  if (id(r.tenant) !== tenant) return fail();
  const state = (v: unknown) => one(v, ['configured', 'missing', 'held'] as const);
  const availableControlRoles = unique(list(r.availableControlRoles, item => {
    const x = record(item, ['id', 'name']);
    return {id: one(x.id, CONTROL), name: name(x.name)};
  }, 7));
  const availableBusinessRoles = unique(list(r.availableBusinessRoles, item => {
    const x = record(item, ['id', 'name', 'desk', 'controlOwner', 'preparationOnly']);
    if (x.preparationOnly !== true) return fail();
    return {id: id(x.id), name: name(x.name), desk: id(x.desk), controlOwner: one(x.controlOwner, CONTROL), preparationOnly: true as const};
  }));
  const roles = new Set([...availableControlRoles, ...availableBusinessRoles].map(x => x.id));
  const configuredModules = unique(list(r.configuredModules, item => {
    const x = record(item, ['id', 'name', 'category', 'disposition', 'risk', 'approval', 'gate', 'roles']);
    const module: ConfiguredModule = {id: id(x.id), name: name(x.name), category: one(x.category, ['skills', 'mcp', 'connector', 'plugin', 'playbook', 'mod', 'unknown']), disposition: one(x.disposition, ['add', 'pointer', 'hold', 'refuse', 'unknown']), risk: one(x.risk, ['low', 'medium', 'high', 'unknown']), approval: one(x.approval, ['yes', 'no', 'unknown']), gate: one(x.gate, ['held', 'approval_required', 'catalog_permitted']), roles: list(x.roles, id)};
    if (module.roles.some(role => !roles.has(role)) || new Set(module.roles).size !== module.roles.length) return fail();
    if (module.gate !== 'held' && (!['add', 'pointer'].includes(module.disposition) || module.category === 'unknown' || module.risk === 'unknown' || module.approval === 'unknown')) return fail();
    const needsApproval = module.approval === 'yes' || module.risk === 'high';
    if (module.gate === 'catalog_permitted' && needsApproval || module.gate === 'approval_required' && !needsApproval) return fail();
    return module;
  }));
  const assignedAgents = unique(list(r.assignedAgents, item => {
    const x = record(item, ['id', 'status']);
    const result = {id: id(x.id), status: one(x.status, ['configured', 'held'] as const)};
    if (result.status === 'configured' && !roles.has(result.id)) return fail();
    return result;
  }));
  const registeredSources = unique(list(r.registeredSources, item => {
    const x = record(item, ['id', 'type', 'admitted']);
    if (typeof x.admitted !== 'boolean') return fail();
    return {id: id(x.id), type: one(x.type, TYPES), admitted: x.admitted};
  }));
  const result: TenantCapabilityMap = {tenant, status: one(r.status, ['source_config_only']), connectionAuth: one(r.connectionAuth, ['unverified']), catalogState: state(r.catalogState), templatesState: state(r.templatesState), enabledState: state(r.enabledState), runtimeState: state(r.runtimeState), runtime: r.runtime === null ? null : id(r.runtime), sourcesState: state(r.sourcesState), configuredModules, assignedAgents, availableControlRoles, availableBusinessRoles, registeredSources};
  if (result.enabledState !== 'configured' && (configuredModules.length || assignedAgents.length)) return fail();
  if ((result.runtimeState === 'configured') !== (result.runtime !== null)) return fail();
  if (result.sourcesState !== 'configured' && registeredSources.length) return fail();
  if (result.catalogState !== 'configured' && (availableControlRoles.length || configuredModules.some(m => m.gate !== 'held'))) return fail();
  if (result.templatesState !== 'configured' && availableBusinessRoles.length) return fail();
  return result;
}

export function tenantCapabilityCountLabels(map?: TenantCapabilityMap): {modules: string; agents: string} {
  if (!map || map.enabledState !== 'configured') {
    const reason = map ? `enablement ${map.enabledState}` : 'capability mapping unavailable';
    return {modules: `Configured module IDs: Unavailable (${reason})`, agents: `Assigned agents: Unavailable (${reason})`};
  }
  return {
    modules: `Configured module IDs: ${map.configuredModules.length} · Held by catalog: ${map.configuredModules.filter(m => m.gate === 'held').length}`,
    agents: `Assigned agents: ${map.assignedAgents.length} · Configuration evidence only`,
  };
}

function line(parent: HTMLElement, value: string): void {
  const p = document.createElement('p'); p.textContent = value; parent.appendChild(p);
}
function group(parent: HTMLElement, title: string, rows: string[]): void {
  const section = document.createElement('details');
  const summary = document.createElement('summary'); summary.textContent = `${title} (${rows.length})`;
  section.appendChild(summary);
  rows.forEach(row => line(section, row));
  if (!rows.length) line(section, 'None recorded');
  parent.appendChild(section);
}
export function renderTenantCapabilityMap(raw: unknown, tenant: string): HTMLElement {
  const section = document.createElement('details');
  section.className = 'oc-tenant-capabilities';
  const summary = document.createElement('summary'); summary.textContent = 'Skills, agents and connections';
  section.appendChild(summary);
  let map: TenantCapabilityMap;
  try { map = parseTenantCapabilityMap(raw, tenant); }
  catch { line(section, 'Capability mapping unavailable — source configuration is missing or invalid.'); return section; }
  line(section, 'Source configuration only · Connection authentication unverified · No live readiness inferred');
  line(section, `Enablement: ${map.enabledState} · Runtime: ${map.runtimeState}${map.runtime ? ` (${map.runtime})` : ''} · Sources: ${map.sourcesState}`);
  line(section, `Public catalog: ${map.catalogState} · Business role catalog: ${map.templatesState}`);
  const displayModule = (m: ConfiguredModule) => `${m.name} [${m.id}] · ${m.category} · ${m.disposition} · risk ${m.risk} · approval ${m.approval} · ${m.gate.replaceAll('_', ' ')}${m.roles.length ? ` · Applicable roles: ${m.roles.join(', ')}` : ''}`;
  group(section, 'Configured skills', map.configuredModules.filter(m => m.category === 'skills').map(displayModule));
  group(section, 'Configured connections — authentication unverified', map.configuredModules.filter(m => ['connector', 'mcp', 'plugin'].includes(m.category)).map(displayModule));
  group(section, 'Configured mods', map.configuredModules.filter(m => m.category === 'mod').map(displayModule));
  group(section, 'Other configured IDs', map.configuredModules.filter(m => ['playbook', 'unknown'].includes(m.category)).map(displayModule));
  group(section, 'Assigned tenant agents — configuration only', map.assignedAgents.map(a => `${a.id} · ${a.status}`));
  group(section, 'Available shared control roles — availability is not assignment', map.availableControlRoles.map(a => `${a.name} [${a.id}]`));
  group(section, 'Available business role templates — preparation only, not instantiated', map.availableBusinessRoles.map(a => `${a.name} [${a.id}] · Desk: ${a.desk} · Control owner: ${a.controlOwner}`));
  group(section, 'Registered sources — admission is not completed ingestion', map.registeredSources.map(s => `${s.id} · ${s.type} · ${s.admitted ? 'admitted' : 'not admitted'}`));
  return section;
}
