import { describe, expect, it } from 'vitest';
import { FLEET_LAYOUT, fleetActivity, fleetNodes } from './fleet-model';
import { derivePresence } from './residents';
import type { OpsSnapshot, SafeActivityRecord } from './ops-contracts';

const now = Date.parse('2026-10-08T12:00:00Z');
function snapshot(): OpsSnapshot {
  return {
    schema: 'snowgloves.cockpit.v1', generatedAt: new Date(now).toISOString(),
    scope: { mode: 'local-private', tenant: 'acme', readOnly: true },
    catalog: { cards: [], agents: [], adapters: [], connectors: [] }, tenants: [], fleet: [],
    fleetNodes: FLEET_LAYOUT.map(({ id, name, wing, profileId }) => ({ id, name, wing, profileId,
      assignment: id === 'mac-coding-2' ? 'planned' : 'configured', evidence: id === 'mac-coding-2' ? 'pending' : 'local',
      sources: ['catalog/fleet-topology.json'], observedAt: null })),
    activity: { events: [], jobs: [], artifacts: [], approvals: [] }, acceptance: [],
    routing: { rules: [], skills: [] }, documents: [], services: [], warnings: [],
    capabilities: { documents: true, planPreview: true, execute: false, enable: false, approve: false },
  };
}
function record(overrides: Partial<SafeActivityRecord> = {}): SafeActivityRecord {
  return { id: 'running', timestamp: new Date(now - 10000).toISOString(), tenant: 'acme', agent: 'cto', kind: 'job',
    status: 'running', jobId: 'job-1', artifactId: null, summary: 'job', nodeId: 'mac-coding-1', ...overrides };
}
function presence(s: OpsSnapshot | null, id = 'mac-coding-1', stale = false) {
  return derivePresence(s ? { ...s, activity: fleetActivity(s, id) } : null, now, stale).find(p => p.slug === 'cto')!;
}

describe('four-island fleet model', () => {
  it('keeps four canonical ordered slots and independent fallback records', () => {
    expect(fleetNodes(null).map(n => n.id)).toEqual(FLEET_LAYOUT.map(n => n.id));
    expect(fleetNodes(null).every(n => n.assignment === 'planned' && n.observedAt === null)).toBe(true);
    const nodes = fleetNodes(null); nodes[0].sources.push('changed');
    expect(fleetNodes(null)[0].sources).toEqual(['catalog/fleet-topology.json']);
    expect(new Set(FLEET_LAYOUT.map(n => `${n.x}:${n.z}`)).size).toBe(4);
  });
  it('isolates exact node and tenant evidence in every activity category', () => {
    const s = snapshot();
    for (const category of ['events', 'jobs', 'artifacts', 'approvals'] as const) {
      s.activity[category] = [record(), record({ id: 'unbound', nodeId: null }), record({ id: 'other', nodeId: 'mac-creative' }), record({ id: 'foreign', tenant: 'foreign' })];
      expect(fleetActivity(s, 'mac-coding-1')[category].map(r => r.id)).toEqual(['running']);
    }
    s.activity.approvals = [];
    expect(presence(s).state).toBe('active');
  });
  it('planned, template, absent and unknown slots cannot claim actual work', () => {
    const s = snapshot(); s.activity.jobs = [record({ nodeId: 'mac-coding-2' })];
    expect(presence(s, 'mac-coding-2').state).toBe('unknown');
    s.scope.mode = 'public-fixtures'; s.fleetNodes!.forEach(n => { n.assignment = 'template'; n.evidence = 'source'; });
    s.activity.jobs = [record()]; expect(presence(s).state).toBe('unknown');
    expect(fleetActivity(s, 'unknown').jobs).toEqual([]);
    expect(fleetActivity(null, 'mac-coding-1').jobs).toEqual([]);
    delete s.fleetNodes; expect(presence(s).state).toBe('unknown');
  });
  it('later unbound cancellation revokes attributed work without creating presence', () => {
    const s = snapshot(); s.activity.jobs = [record(), record({ id: 'cancel', agent: null, nodeId: null, status: 'cancelled', timestamp: new Date(now - 1000).toISOString() })];
    expect(fleetActivity(s, 'mac-coding-1').jobs).toEqual([]);
    expect(presence(s).state).toBe('unknown');
  });
  it('retains exact-node terminal authority with absent resident identity', () => {
    const s = snapshot(); s.activity.jobs = [record(), record({ id: 'cancel', agent: null, status: 'cancelled', timestamp: new Date(now - 1000).toISOString() })];
    expect(fleetActivity(s, 'mac-coding-1').jobs.map(r => r.id)).toEqual(['cancel']);
    expect(presence(s).state).toBe('unknown');
  });
  it('another node terminal with a colliding job id does not cancel selected work', () => {
    const s = snapshot(); s.activity.jobs = [record(), record({ id: 'cancel', nodeId: 'mac-coding-2', status: 'cancelled', timestamp: new Date(now - 1000).toISOString() })];
    expect(presence(s).state).toBe('active');
  });
  it('older, invalid and future unbound cancellations cannot revoke recent work', () => {
    for (const timestamp of [new Date(now - 20000).toISOString(), new Date(now + 5000).toISOString(), '2026-02-30T12:00:00Z', 'invalid']) {
      const s = snapshot(); s.activity.jobs = [record(), record({ id: 'cancel', agent: null, nodeId: null, status: 'cancelled', timestamp })];
      expect(presence(s).state).toBe('active');
    }
  });
  it('keeps freshness, future dates and disconnected state under resident derivation', () => {
    const s = snapshot(); s.activity.jobs = [record()];
    expect(presence(s, 'mac-coding-1', true).state).toBe('unknown');
    s.activity.jobs = [record({ timestamp: new Date(now + 1000).toISOString() })]; expect(presence(s).state).toBe('unknown');
    s.activity.jobs = [record({ timestamp: new Date(now - 1200000).toISOString() })]; expect(presence(s).state).toBe('unknown');
    expect(presence(null).state).toBe('unknown');
  });
});
