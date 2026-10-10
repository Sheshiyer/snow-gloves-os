import { describe, it, expect } from 'vitest';
import { RESIDENTS, derivePresence, demoPresence, type ResidentSlug } from './residents';
import type { OpsSnapshot, SafeActivityRecord } from './ops-contracts';

function createSnapshotFixture(overrides: Partial<OpsSnapshot> = {}): OpsSnapshot {
  return {
    schema: 'snowgloves.cockpit.v1',
    generatedAt: '2025-01-01T00:00:00.000Z',
    scope: {
      mode: 'local-private',
      tenant: 'test-tenant',
      readOnly: true,
    },
    catalog: {
      cards: [],
      agents: [],
      adapters: [],
      connectors: [],
    },
    tenants: [],
    fleet: [],
    activity: {
      events: [],
      jobs: [],
      artifacts: [],
      approvals: [],
    },
    acceptance: [],
    routing: {
      rules: [],
      skills: [],
    },
    documents: [],
    services: [],
    warnings: [],
    capabilities: {
      documents: true,
      planPreview: true,
      execute: false,
      enable: false,
      approve: false,
    },
    ...overrides,
  };
}

function makeRecord(partial: Partial<SafeActivityRecord>): SafeActivityRecord {
  return {
    id: 'rec-1',
    timestamp: '2025-01-01T00:00:00.000Z',
    tenant: 'test-tenant',
    agent: 'ceo',
    kind: 'job',
    status: 'running',
    jobId: 'job-1',
    artifactId: null,
    summary: 'Execution summary with potential sensitive details',
    sources: ['agents/ceo/IDENTITY.md'],
    ...partial,
  };
}

describe('strict timestamp and scope evidence', () => {
  it.each(['2025-01-01T00:00:00', '2025-02-30T00:00:00Z', '2025-13-01T00:00:00Z'])('rejects ambiguous or normalized invalid date %s', timestamp => {
    const snapshot = createSnapshotFixture();
    snapshot.activity.jobs = [makeRecord({timestamp})];
    const normalized = Date.parse(timestamp);
    const presence = derivePresence(snapshot, Number.isFinite(normalized) ? normalized : Date.parse('2025-03-02T00:00:00Z'));
    expect(presence.every(item => item.state === 'unknown')).toBe(true);
  });
  it('does not silently normalize a selected tenant scope', () => {
    const snapshot = createSnapshotFixture();
    snapshot.scope.tenant = ' test-tenant ';
    snapshot.activity.jobs = [makeRecord({})];
    expect(derivePresence(snapshot, Date.parse('2025-01-01T00:00:00Z')).every(item => item.state === 'unknown')).toBe(true);
  });
});

describe('job authority without resident identity', () => {
  const now = Date.parse('2025-01-01T00:00:00Z');
  it.each(['completed', 'failed'])('newer null-agent %s revokes same-job walking without assigning rest', status => {
    const snapshot = createSnapshotFixture();
    snapshot.activity.events = [makeRecord({timestamp: new Date(now - 5000).toISOString()})];
    snapshot.activity.jobs = [makeRecord({id: 'terminal', agent: null, status, timestamp: new Date(now - 2000).toISOString()})];
    const result = derivePresence(snapshot, now);
    expect(result.every(item => item.state === 'unknown' && item.evidence === 'unobserved')).toBe(true);
  });
  it.each([
    {tenant: 'another-tenant', timestamp: new Date(now - 2000).toISOString()},
    {tenant: 'test-tenant', timestamp: new Date(now - 6000).toISOString()},
    {tenant: 'test-tenant', timestamp: new Date(now + 1).toISOString()},
  ])('unrelated, old or future terminal authority cannot suppress current work: %j', terminal => {
    const snapshot = createSnapshotFixture();
    snapshot.activity.events = [makeRecord({timestamp: new Date(now - 5000).toISOString()})];
    snapshot.activity.jobs = [makeRecord({id: 'terminal', agent: null, status: 'completed', ...terminal})];
    expect(derivePresence(snapshot, now).find(item => item.slug === 'ceo')?.state).toBe('active');
  });
});

describe('residents static definitions', () => {
  it('has exactly 7 residents in the strict canonical order', () => {
    const expectedSlugs: ResidentSlug[] = [
      'ceo',
      'cto',
      'chief-of-staff',
      'librarian',
      'interpreter',
      'dispatcher',
      'sentinel',
    ];
    expect(RESIDENTS.map((r) => r.slug)).toEqual(expectedSlugs);
    expect(RESIDENTS.length).toBe(7);
  });

  it('has immutable definitions with valid props, stations, and exact source references', () => {
    for (const r of RESIDENTS) {
      expect(r.nodeId).toBe(`agent-${r.slug}`);
      expect(r.sources).toEqual([`agents/${r.slug}/IDENTITY.md`, `agents/${r.slug}/SOUL.md`]);
      expect(r.route.length).toBeGreaterThanOrEqual(3);
      expect(r.route[0]).toBe(r.nodeId);
      expect(r.route[r.route.length - 1]).toBe(r.nodeId);
      expect(r.prop).toBeDefined();
      expect(r.station).toBeDefined();
    }
    expect(Object.isFrozen(RESIDENTS)).toBe(true);
  });
});

describe('derivePresence edge cases & baseline defensive checks', () => {
  const nowMs = 1735689600000; // 2025-01-01T00:00:00.000Z

  it('returns all 7 unknown unobserved when snapshot is null', () => {
    const pres = derivePresence(null, nowMs);
    expect(pres.length).toBe(7);
    expect(pres.every((p) => p.state === 'unknown' && p.evidence === 'unobserved')).toBe(true);
    expect(pres[0].label).toBe('No active evidence');
  });

  it('returns all unknown when stale flag is true', () => {
    const snap = createSnapshotFixture();
    const pres = derivePresence(snap, nowMs, true);
    expect(pres.every((p) => p.state === 'unknown' && p.evidence === 'unobserved')).toBe(true);
    expect(pres[0].reason).toContain('stale');
  });

  it('returns all unknown when nowMs is invalid or NaN', () => {
    const snap = createSnapshotFixture();
    const pres = derivePresence(snap, Number.NaN);
    expect(pres.every((p) => p.state === 'unknown' && p.evidence === 'unobserved')).toBe(true);
  });

  it('returns all unknown when tenant scope is missing or empty', () => {
    const snap = createSnapshotFixture({
      scope: { mode: 'public-fixtures', tenant: null, readOnly: true },
    });
    const pres = derivePresence(snap, nowMs);
    expect(pres.every((p) => p.state === 'unknown' && p.evidence === 'unobserved')).toBe(true);
  });

  it('does not infer presence from service reachable counts or catalog entries', () => {
    const snap = createSnapshotFixture({
      services: [
        {
          id: 'svc-1',
          label: 'Inference',
          url: 'http://localhost:8080',
          state: 'reachable',
          checkedAt: new Date(nowMs).toISOString(),
          latencyMs: 12,
          scope: 'endpoint-only',
        },
      ],
      activity: { events: [], jobs: [], artifacts: [], approvals: [] },
    });
    const pres = derivePresence(snap, nowMs);
    expect(pres.every((p) => p.state === 'unknown' && p.evidence === 'unobserved')).toBe(true);
  });
});

describe('derivePresence active state & recency boundaries', () => {
  const nowMs = 1735689600000; // 2025-01-01T00:00:00.000Z

  it('derives active state for valid recent active job', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [],
        jobs: [
          makeRecord({
            id: 'job-rec-1',
            agent: 'ceo',
            status: 'running',
            timestamp: new Date(nowMs - 5000).toISOString(),
          }),
        ],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const ceo = pres.find((p) => p.slug === 'ceo');
    expect(ceo?.state).toBe('active');
    expect(ceo?.evidence).toBe('observed');
    expect(ceo?.label).toBe('Active');
    expect(ceo?.recordId).toBe('job-rec-1');
    expect(ceo?.observedAt).toBe(new Date(nowMs - 5000).toISOString());
  });

  it('handles exact boundary: <= 120000ms is active, 120001ms is unknown', () => {
    const snapAt120 = createSnapshotFixture({
      activity: {
        events: [],
        jobs: [
          makeRecord({
            id: 'rec-120',
            agent: 'cto',
            status: 'running',
            timestamp: new Date(nowMs - 120000).toISOString(),
          }),
        ],
        artifacts: [],
        approvals: [],
      },
    });
    const pres120 = derivePresence(snapAt120, nowMs);
    expect(pres120.find((p) => p.slug === 'cto')?.state).toBe('active');

    const snapAt121 = createSnapshotFixture({
      activity: {
        events: [],
        jobs: [
          makeRecord({
            id: 'rec-121',
            agent: 'cto',
            status: 'running',
            timestamp: new Date(nowMs - 120001).toISOString(),
          }),
        ],
        artifacts: [],
        approvals: [],
      },
    });
    const pres121 = derivePresence(snapAt121, nowMs);
    const cto121 = pres121.find((p) => p.slug === 'cto');
    expect(cto121?.state).toBe('unknown');
    expect(cto121?.evidence).toBe('unobserved');
    expect(cto121?.label).toBe('No recent active evidence');
    expect(cto121?.recordId).toBeNull();
  });

  it('rejects future timestamps strictly with no future tolerance', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'future-rec',
            agent: 'sentinel',
            status: 'running',
            timestamp: new Date(nowMs + 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const sentinel = pres.find((p) => p.slug === 'sentinel');
    expect(sentinel?.state).toBe('unknown');
  });

  it('accepts numeric unix timestamps in seconds and milliseconds', () => {
    const secSnap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'sec-rec',
            agent: 'dispatcher',
            status: 'executing',
            timestamp: String((nowMs - 10000) / 1000),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const presSec = derivePresence(secSnap, nowMs);
    expect(presSec.find((p) => p.slug === 'dispatcher')?.state).toBe('active');

    const msSnap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'ms-rec',
            agent: 'interpreter',
            status: 'in_progress',
            timestamp: String(nowMs - 15000),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const presMs = derivePresence(msSnap, nowMs);
    expect(presMs.find((p) => p.slug === 'interpreter')?.state).toBe('active');
  });

  it('supports epoch 0 timestamp when nowMs is 0', () => {
    const zeroSnap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'zero-rec',
            agent: 'librarian',
            status: 'running',
            timestamp: '0',
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(zeroSnap, 0);
    expect(pres.find((p) => p.slug === 'librarian')?.state).toBe('active');
  });
});

describe('derivePresence tenant matching and slug isolation', () => {
  const nowMs = 1735689600000;

  it('ignores records from another tenant', () => {
    const snap = createSnapshotFixture({
      scope: { mode: 'local-private', tenant: 'tenant-a', readOnly: true },
      activity: {
        events: [
          makeRecord({
            id: 'other-tenant-rec',
            tenant: 'tenant-b',
            agent: 'ceo',
            status: 'running',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    expect(pres.find((p) => p.slug === 'ceo')?.state).toBe('unknown');
  });

  it('does not bleed activity across different agent slugs', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-cto',
            agent: 'cto',
            status: 'running',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    expect(pres.find((p) => p.slug === 'cto')?.state).toBe('active');
    expect(pres.find((p) => p.slug === 'ceo')?.state).toBe('unknown');
    expect(pres.find((p) => p.slug === 'sentinel')?.state).toBe('unknown');
  });
});

describe('derivePresence job resolution & supersession', () => {
  const nowMs = 1735689600000;

  it('terminal status on same job supersedes older active status regardless of array ordering', () => {
    const activeFirstSnap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-active',
            jobId: 'job-shared',
            agent: 'ceo',
            status: 'running',
            timestamp: new Date(nowMs - 5000).toISOString(),
          }),
          makeRecord({
            id: 'rec-completed',
            jobId: 'job-shared',
            agent: 'ceo',
            status: 'completed',
            timestamp: new Date(nowMs - 2000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres1 = derivePresence(activeFirstSnap, nowMs);
    expect(pres1.find((p) => p.slug === 'ceo')?.state).toBe('resting');
    expect(pres1.find((p) => p.slug === 'ceo')?.recordId).toBe('rec-completed');

    const completedFirstSnap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-completed',
            jobId: 'job-shared',
            agent: 'ceo',
            status: 'completed',
            timestamp: new Date(nowMs - 2000).toISOString(),
          }),
          makeRecord({
            id: 'rec-active',
            jobId: 'job-shared',
            agent: 'ceo',
            status: 'running',
            timestamp: new Date(nowMs - 5000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres2 = derivePresence(completedFirstSnap, nowMs);
    expect(pres2.find((p) => p.slug === 'ceo')?.state).toBe('resting');
    expect(pres2.find((p) => p.slug === 'ceo')?.recordId).toBe('rec-completed');
  });

  it('handles same timestamp tie by preferring terminal over active to prevent false walking', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-a',
            jobId: 'job-tie',
            agent: 'librarian',
            status: 'running',
            timestamp: new Date(nowMs - 5000).toISOString(),
          }),
          makeRecord({
            id: 'rec-b',
            jobId: 'job-tie',
            agent: 'librarian',
            status: 'succeeded',
            timestamp: new Date(nowMs - 5000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const lib = pres.find((p) => p.slug === 'librarian');
    expect(lib?.state).toBe('resting');
  });

  it('allows active record on different job to remain active even if another job is completed', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'job-old-done',
            jobId: 'job-old',
            agent: 'interpreter',
            status: 'completed',
            timestamp: new Date(nowMs - 10000).toISOString(),
          }),
          makeRecord({
            id: 'job-new-active',
            jobId: 'job-new',
            agent: 'interpreter',
            status: 'started',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const interp = pres.find((p) => p.slug === 'interpreter');
    expect(interp?.state).toBe('active');
    expect(interp?.recordId).toBe('job-new-active');
  });

  it('supersedes active when a newer unknown status arrives on the same job', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-1',
            jobId: 'job-unknown-next',
            agent: 'dispatcher',
            status: 'running',
            timestamp: new Date(nowMs - 10000).toISOString(),
          }),
          makeRecord({
            id: 'rec-2',
            jobId: 'job-unknown-next',
            agent: 'dispatcher',
            status: 'unrecognized_custom_status',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const disp = pres.find((p) => p.slug === 'dispatcher');
    expect(disp?.state).toBe('unknown');
  });
});

describe('derivePresence approval handling & artifacts', () => {
  const nowMs = 1735689600000;

  it('marks agent held when pending approval exists, even if older than 120s', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [],
        jobs: [],
        artifacts: [],
        approvals: [
          makeRecord({
            id: 'appr-1',
            jobId: 'job-gate',
            agent: 'sentinel',
            kind: 'approval',
            status: 'pending',
            timestamp: new Date(nowMs - 300000).toISOString(),
          }),
        ],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const sentinel = pres.find((p) => p.slug === 'sentinel');
    expect(sentinel?.state).toBe('held');
    expect(sentinel?.evidence).toBe('observed');
    expect(sentinel?.label).toBe('Approval held');
    expect(sentinel?.recordId).toBe('appr-1');
  });

  it('clears held state when approval is approved/resolved on same job', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [],
        jobs: [],
        artifacts: [],
        approvals: [
          makeRecord({
            id: 'appr-1',
            jobId: 'job-gate',
            agent: 'sentinel',
            kind: 'approval',
            status: 'pending',
            timestamp: new Date(nowMs - 300000).toISOString(),
          }),
          makeRecord({
            id: 'appr-2',
            jobId: 'job-gate',
            agent: 'sentinel',
            kind: 'approval',
            status: 'approved',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const sentinel = pres.find((p) => p.slug === 'sentinel');
    expect(sentinel?.state).toBe('unknown');
    expect(sentinel?.evidence).toBe('unobserved');
  });

  it('ignores artifacts and prepared job status from activating agent', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [],
        jobs: [
          makeRecord({
            id: 'job-prepared',
            agent: 'cto',
            status: 'prepared',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        artifacts: [
          makeRecord({
            id: 'art-1',
            agent: 'cto',
            kind: 'artifact',
            status: 'created',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    expect(pres.find((p) => p.slug === 'cto')?.state).toBe('unknown');
  });

  it('old completed record stays resting and observed without live health claims', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-old-done',
            agent: 'chief-of-staff',
            status: 'completed',
            timestamp: new Date(nowMs - 600000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const cos = pres.find((p) => p.slug === 'chief-of-staff');
    expect(cos?.state).toBe('resting');
    expect(cos?.evidence).toBe('observed');
    expect(cos?.recordId).toBe('rec-old-done');
  });
});

describe('derivePresence sanitization & input immutability', () => {
  const nowMs = 1735689600000;

  it('never leaks malicious summary or source fields into reason text', () => {
    const maliciousSummary = '<script>evilPayload()</script> token:xyz';
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-safe',
            agent: 'ceo',
            status: 'running',
            summary: maliciousSummary,
            sources: ['malicious/source.md'],
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const pres = derivePresence(snap, nowMs);
    const ceo = pres.find((p) => p.slug === 'ceo');
    expect(ceo?.reason).not.toContain(maliciousSummary);
    expect(ceo?.reason).not.toContain('evilPayload');
  });

  it('does not mutate input snapshot arrays', () => {
    const snap = createSnapshotFixture({
      activity: {
        events: [
          makeRecord({
            id: 'rec-1',
            agent: 'ceo',
            status: 'running',
            timestamp: new Date(nowMs - 1000).toISOString(),
          }),
        ],
        jobs: [],
        artifacts: [],
        approvals: [],
      },
    });
    const eventsCopy = [...snap.activity.events];
    derivePresence(snap, nowMs);
    expect(snap.activity.events).toEqual(eventsCopy);
  });
});

describe('demoPresence', () => {
  it('defaults all 7 residents to resting in demo mode', () => {
    const pres = demoPresence();
    expect(pres.length).toBe(7);
    expect(pres.every((p) => p.state === 'resting' && p.evidence === 'demo')).toBe(true);
    expect(pres.every((p) => p.label === 'Demo resting')).toBe(true);
    expect(pres.every((p) => p.recordId === null && p.observedAt === null)).toBe(true);
  });

  it('activates exactly one resident when valid slug provided', () => {
    const pres = demoPresence('cto');
    const cto = pres.find((p) => p.slug === 'cto');
    expect(cto?.state).toBe('active');
    expect(cto?.evidence).toBe('demo');
    expect(cto?.label).toBe('Demo walking');

    const others = pres.filter((p) => p.slug !== 'cto');
    expect(others.every((p) => p.state === 'resting' && p.label === 'Demo resting')).toBe(true);
  });

  it('falls back to all resting if an invalid slug is passed', () => {
    // @ts-expect-error test runtime invalid slug
    const pres = demoPresence('invalid-slug');
    expect(pres.every((p) => p.state === 'resting')).toBe(true);
  });

  it('returns fresh array and objects on every invocation', () => {
    const first = demoPresence('ceo');
    const second = demoPresence('ceo');
    expect(first).not.toBe(second);
    expect(first[0]).not.toBe(second[0]);
  });
});
