import { afterEach, describe, expect, it, vi } from 'vitest';
// @ts-expect-error The browser tsconfig intentionally excludes Node types; this test runs in Vitest.
import { execFileSync } from 'node:child_process';
import { parseTenantCapabilityMap, renderTenantCapabilityMap, tenantCapabilityCountLabels, type TenantCapabilityMap } from './tenant-map';

function fixture(): TenantCapabilityMap {
  return {tenant: 'acme', status: 'source_config_only', connectionAuth: 'unverified', catalogState: 'configured', templatesState: 'configured', enabledState: 'configured', runtimeState: 'missing', runtime: null, sourcesState: 'configured', configuredModules: [{id: 'skill-a', name: 'Skill A', category: 'skills', disposition: 'add', risk: 'high', approval: 'yes', gate: 'approval_required', roles: ['cto']}, {id: 'connector-a', name: 'Connector A', category: 'connector', disposition: 'pointer', risk: 'low', approval: 'no', gate: 'catalog_permitted', roles: []}], assignedAgents: [], availableControlRoles: [{id: 'cto', name: 'Technology'}], availableBusinessRoles: [{id: 'writer', name: 'Writer', desk: 'editorial', controlOwner: 'cto', preparationOnly: true}], registeredSources: [{id: 'brand-docs', type: 'filesystem', admitted: true}]};
}

describe('source configuration contract', () => {
  it('keeps available roles, assigned agents, configuration gates and live proof distinct', () => {
    const parsed = parseTenantCapabilityMap(fixture(), 'acme');
    expect(parsed.assignedAgents).toEqual([]);
    expect(parsed.availableControlRoles).toHaveLength(1);
    expect(parsed.availableBusinessRoles[0].preparationOnly).toBe(true);
    expect(parsed.connectionAuth).toBe('unverified');
    expect(parsed.runtimeState).toBe('missing');
    expect(parsed.configuredModules[0].gate).toBe('approval_required');
  });

  it('requires approval for high risk independently of the authoritative approval field', () => {
    const raw = fixture();
    raw.configuredModules[0].approval = 'no';
    expect(parseTenantCapabilityMap(raw, 'acme').configuredModules[0]).toMatchObject({risk: 'high', approval: 'no', gate: 'approval_required'});
    raw.configuredModules[0].gate = 'catalog_permitted';
    expect(() => parseTenantCapabilityMap(raw, 'acme')).toThrow('Invalid tenant capability map');
  });

  it('distinguishes unavailable mappings or enablement from configured empty lists', () => {
    const absent = tenantCapabilityCountLabels();
    expect(absent.modules).toContain('Unavailable');
    expect(absent.agents).toContain('Unavailable');
    expect(JSON.stringify(absent)).not.toContain(': 0');
    const empty = fixture();
    empty.configuredModules = [];
    expect(tenantCapabilityCountLabels(empty).modules).toContain('Configured module IDs: 0');
    expect(tenantCapabilityCountLabels(empty).agents).toContain('Assigned agents: 0');
    empty.enabledState = 'missing';
    expect(tenantCapabilityCountLabels(empty).modules).toContain('Unavailable (enablement missing)');
    empty.enabledState = 'held';
    expect(tenantCapabilityCountLabels(empty).agents).toContain('Unavailable (enablement held)');
  });

  it.each([
    (x: any) => { x.tenant = 'foreign'; },
    (x: any) => { x.status = 'live'; },
    (x: any) => { x.connectionAuth = 'verified'; },
    (x: any) => { x.notes = 'secret data'; },
    (x: any) => { x.registeredSources[0].path = '/private/hidden'; },
    (x: any) => { x.registeredSources[0].type = 'https://private'; },
    (x: any) => { x.registeredSources[0].admitted = 'yes'; },
    (x: any) => { x.configuredModules[0].name = '<img src=x onerror=alert(1)>'; },
    (x: any) => { x.configuredModules[0].id = 'token-private'; },
    (x: any) => { x.configuredModules[0].id = 'x'.repeat(65); },
    (x: any) => { x.configuredModules[0].disposition = 'refuse'; },
    (x: any) => { x.configuredModules[0].disposition = 'hold'; },
    (x: any) => { x.configuredModules[0].gate = 'catalog_permitted'; },
    (x: any) => { x.configuredModules[0].roles = ['unknown']; },
    (x: any) => { x.configuredModules.push(x.configuredModules[0]); },
    (x: any) => { x.availableControlRoles = [{id: 'unknown', name: 'Unknown'}]; },
    (x: any) => { x.availableBusinessRoles[0].preparationOnly = false; },
    (x: any) => { x.assignedAgents = [{id: 'unknown', status: 'configured'}]; },
    (x: any) => { x.enabledState = 'held'; },
    (x: any) => { x.runtimeState = 'configured'; },
    (x: any) => { x.runtime = 'codex'; },
    (x: any) => { x.catalogState = 'held'; },
    (x: any) => { x.templatesState = 'held'; },
    (x: any) => { x.sourcesState = 'missing'; },
    (x: any) => { x.registeredSources = Array(129).fill(x.registeredSources[0]); },
  ])('rejects malformed, unsafe or contradictory responses %#', mutate => {
    const raw = fixture(); mutate(raw);
    expect(() => parseTenantCapabilityMap(raw, 'acme')).toThrow('Invalid tenant capability map');
  });

  it('accepts the real backend projection and public seven/nineteen role catalogs', () => {
    const raw = execFileSync('python3', ['-c', 'import sys,json; from pathlib import Path; sys.path.insert(0,"../../scripts"); from lib.cockpit_tenant_map import capability_map; r=Path("../..").resolve(); print(json.dumps(capability_map(r,r/"tenants"/"acme")))'], {encoding: 'utf8'});
    const map = parseTenantCapabilityMap(JSON.parse(raw), 'acme');
    expect(map.availableControlRoles).toHaveLength(7);
    expect(map.availableBusinessRoles).toHaveLength(19);
    expect(map.enabledState).toBe('missing');
    expect(map.runtimeState).toBe('missing');
    expect(map.assignedAgents).toEqual([]);
  });
});

// Minimal DOM harness deliberately throws if the renderer tries to inject markup.
class Element {
  children: Element[] = []; textContent = ''; className = '';
  constructor(public tagName: string) {}
  appendChild(child: Element) { this.children.push(child); return child; }
  set innerHTML(_: string) { throw new Error('Unsafe markup rendering'); }
  text(): string { return [this.textContent, ...this.children.map(c => c.text())].join('\n'); }
}
afterEach(() => vi.unstubAllGlobals());
describe('capability section rendering', () => {
  it('uses nested collapsed disclosures and explicit source boundaries without HTML injection', () => {
    vi.stubGlobal('document', {createElement: (tag: string) => new Element(tag)});
    const rendered = renderTenantCapabilityMap(fixture(), 'acme') as unknown as Element;
    expect(rendered.tagName).toBe('details');
    expect(rendered.children[0].tagName).toBe('summary');
    const content = rendered.text();
    for (const label of ['Skills, agents and connections', 'Configured skills (1)', 'Assigned tenant agents — configuration only (0)', 'Available shared control roles', 'preparation only, not instantiated', 'Runtime: missing', 'Connection authentication unverified', 'approval required', 'Applicable roles: cto', 'admission is not completed ingestion']) expect(content).toContain(label);
  });
  it('renders an unavailable notice and none of an invalid response', () => {
    vi.stubGlobal('document', {createElement: (tag: string) => new Element(tag)});
    const raw = {...fixture(), connectionAuth: 'verified', notes: 'PRIVATE_VALUE'};
    const content = (renderTenantCapabilityMap(raw, 'acme') as unknown as Element).text();
    expect(content).toContain('Capability mapping unavailable');
    expect(content).not.toContain('PRIVATE_VALUE');
    expect(content).not.toContain('Skill A');
  });
});
