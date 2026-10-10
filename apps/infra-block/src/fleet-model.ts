import type { OpsSnapshot, OpsSnapshotFleetNode, SafeActivityRecord } from './ops-contracts';

/** Logical chart positions express the world design, never a hardware location. */
export const FLEET_LAYOUT = Object.freeze([
  Object.freeze({ id: 'mac-coding-1', name: 'Mac Coding 01', wing: 'coding' as const, profileId: 'node-coding', x: -180, z: -110, color: '#92afa0' }),
  Object.freeze({ id: 'mac-coding-2', name: 'Mac Coding 02', wing: 'coding' as const, profileId: 'node-coding', x: 180, z: -110, color: '#96adb8' }),
  Object.freeze({ id: 'mac-creative', name: 'Mac Creative', wing: 'design' as const, profileId: 'node-design', x: -180, z: 180, color: '#c88d77' }),
  Object.freeze({ id: 'mac-marketing', name: 'Mac Marketing', wing: 'marketing' as const, profileId: 'node-marketing', x: 180, z: 180, color: '#d3bc7c' }),
]);

export interface FleetProjection {
  snapshot: OpsSnapshot | null;
  scopeMode: 'public-fixtures' | 'local-private' | null;
  tenant: string | null;
  stale: boolean;
  source: 'api' | 'fixture' | 'unavailable';
}

export function fleetNodes(snapshot: OpsSnapshot | null): OpsSnapshotFleetNode[] {
  return FLEET_LAYOUT.map(slot => {
    const projected = snapshot?.fleetNodes?.find(node => node.id === slot.id);
    if (projected) return { ...projected, sources: [...projected.sources] };
    return {
      id: slot.id, name: slot.name, wing: slot.wing, profileId: slot.profileId,
      assignment: 'planned', evidence: 'pending', sources: ['catalog/fleet-topology.json'], observedAt: null,
    };
  });
}

const TERMINAL = new Set(['completed', 'complete', 'succeeded', 'success', 'failed', 'cancelled', 'canceled', 'done', 'finished', 'idle', 'resting', 'stopped']);

function timestamp(record: SafeActivityRecord): number | null {
  if (typeof record.timestamp !== 'string') return null;
  const raw = record.timestamp.trim();
  let ms: number;
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const n = Number(raw);
    ms = n < 1e12 ? n * 1000 : n;
  } else {
    const iso = /^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.exec(raw);
    if (!iso) return null;
    const calendar = new Date(`${iso[1]}-${iso[2]}-${iso[3]}T00:00:00Z`);
    if (calendar.getUTCFullYear() !== Number(iso[1]) || calendar.getUTCMonth() + 1 !== Number(iso[2]) || calendar.getUTCDate() !== Number(iso[3])) return null;
    ms = Date.parse(raw);
  }
  return Number.isFinite(ms) && ms >= 0 && ms <= 8640000000000000 ? ms : null;
}

const emptyActivity = (): OpsSnapshot['activity'] => ({ events: [], jobs: [], artifacts: [], approvals: [] });

/** Filter device attribution before resident derivation. Unbound work stays unbound.
 * A later unbound cancellation may revoke a known job; it never creates presence.
 */
export function fleetActivity(snapshot: OpsSnapshot | null, nodeId: string): OpsSnapshot['activity'] {
  if (!snapshot || !FLEET_LAYOUT.some(node => node.id === nodeId)) return emptyActivity();
  const node = fleetNodes(snapshot).find(candidate => candidate.id === nodeId);
  if (!node || node.assignment !== 'configured' || snapshot.scope.mode !== 'local-private') return emptyActivity();
  const tenant = snapshot.scope.tenant;
  if (!tenant) return emptyActivity();
  // generatedAt bounds revocation evidence; future terminal records are not authoritative.
  const snapshotMs = Date.parse(snapshot.generatedAt);
  const terminalJobs = new Map<string, number>();
  for (const record of [...snapshot.activity.events, ...snapshot.activity.jobs]) {
    if (record.nodeId != null && record.nodeId !== nodeId) continue;
    if (record.tenant !== tenant || !record.jobId?.trim() || !TERMINAL.has(record.status.trim().toLowerCase())) continue;
    const ms = timestamp(record);
    if (ms === null || !Number.isFinite(snapshotMs) || ms > snapshotMs) continue;
    const key = record.jobId.trim();
    terminalJobs.set(key, Math.max(terminalJobs.get(key) ?? -1, ms));
  }
  const select = (records: SafeActivityRecord[]): SafeActivityRecord[] => records.filter(record => {
    if (record.nodeId !== nodeId || record.tenant !== tenant) return false;
    const revokedAt = record.jobId ? terminalJobs.get(record.jobId.trim()) : undefined;
    const ms = timestamp(record);
    // Attributed terminal evidence is retained so derivePresence can show resting.
    return TERMINAL.has(record.status.trim().toLowerCase()) || revokedAt === undefined || ms === null || ms > revokedAt;
  });
  return {
    events: select(snapshot.activity.events), jobs: select(snapshot.activity.jobs),
    artifacts: select(snapshot.activity.artifacts), approvals: select(snapshot.activity.approvals),
  };
}
