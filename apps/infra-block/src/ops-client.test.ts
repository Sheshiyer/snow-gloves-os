import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  OpsClientError,
  loadDocument,
  loadSnapshot,
  previewPlan,
  validateDocument,
  validatePlanPreview,
  validateSnapshot,
} from './ops-client';
import type { OpsSnapshot, PlanPreview, PlanRequest } from './ops-contracts';
import { FLEET_LAYOUT } from './fleet-model';

const VALID_SNAPSHOT_FIXTURE: OpsSnapshot = {
  schema: 'snowgloves.cockpit.v1',
  generatedAt: '2025-01-15T12:00:00Z',
  scope: {
    mode: 'public-fixtures',
    tenant: 'tenant-a',
    readOnly: true,
  },
  catalog: {
    cards: [
      {
        id: 'card-1',
        name: 'Card 1',
        category: 'skills',
        kind: 'tool',
        disposition: 'add',
        repo: 'repo-1',
        source: 'source-1',
        risk: 'low',
        approval: 'no',
        agents: ['agent-1'],
        runtimes: ['node20'],
        summary: 'Card summary',
        enableable: true,
      },
    ],
    agents: [
      {
        slug: 'agent-1',
        role: 'tester',
        layer: 'base',
        skill_count: 5,
        hooks: ['pre-run'],
      },
    ],
    adapters: [
      {
        schema: 'snowgloves.adapter.v1',
        id: 'adapter-1',
        name: 'Adapter One',
        homepage: 'https://example.com',
        question_tool: 'qtool',
        plan_mode: 'auto',
        paths: { main: 'dist/index.js' },
        formats: { out: 'json' },
        install: ['npm install'],
        plugin_install: null,
        notes: 'Adapter notes',
        verify: true,
      },
    ],
    connectors: [
      {
        id: 'connector-1',
        auth: 'bearer',
        capabilities: [{ id: 'read', risk: 'low', approval: 'no' }],
        note: 'Connector note',
        base_url: 'https://api.example.com',
      },
    ],
  },
  tenants: [
    {
      slug: 'tenant-a',
      name: 'Tenant Alpha',
      primaryRuntime: 'node20',
      agents: ['agent-1'],
      enabledModules: ['mod-1'],
      approvalCounts: { pending: 1, approved: 2, rejected: 0 },
      sourceCount: 3,
      sources: ['src/a'],
      availability: 'fixture',
      warnings: [],
    },
  ],
  fleet: [
    {
      id: 'fleet-1',
      name: 'Fleet 1',
      wing: 'north',
      runtime: 'node20',
      profile: { cpu: 4, nested: { active: true } },
      sources: ['fleet/src'],
      evidence: 'source',
    },
  ],
  activity: {
    events: [
      {
        id: 'evt-1',
        timestamp: '2025-01-15T11:00:00Z',
        tenant: 'tenant-a',
        agent: 'agent-1',
        kind: 'audit',
        status: 'ok',
        jobId: null,
        artifactId: null,
        summary: 'event logged',
      },
    ],
    jobs: [],
    artifacts: [],
    approvals: [],
  },
  acceptance: [
    {
      id: 'acc-1',
      criterion: 'Must pass',
      status: 'accepted',
      source: 'ISA.md',
    },
  ],
  routing: {
    rules: [
      {
        id: 'rule-1',
        agent: 'agent-1',
        hook: 'pre-run',
        globs: ['**/*.ts'],
        skills: ['skill-1'],
        source: 'rule-source',
      },
    ],
    skills: [{ name: 'skill-1', enabled: true }],
  },
  documents: [
    {
      path: 'docs/guide.md',
      title: 'Guide',
      kind: 'markdown',
      bytes: 1024,
    },
  ],
  services: [
    {
      id: 'svc-1',
      label: 'Main API',
      url: 'https://service.internal',
      state: 'reachable',
      checkedAt: '2025-01-15T11:59:00Z',
      latencyMs: 42,
      scope: 'endpoint-only',
    },
  ],
  warnings: [
    {
      code: 'WARN_001',
      message: 'Notice',
    },
  ],
  capabilities: {
    documents: true,
    planPreview: true,
    execute: false,
    enable: false,
    approve: false,
  },
};

describe('canonical fleet node validation', () => {
  function withNodes() {
    return { ...structuredClone(VALID_SNAPSHOT_FIXTURE), fleetNodes: FLEET_LAYOUT.map(({ id, name, wing, profileId }) => ({
      id, name, wing, profileId, assignment: 'template', evidence: 'source', sources: ['catalog/fleet-topology.json'], observedAt: null,
    })) };
  }
  it('accepts canonical templates and strips unknown host/control fields', () => {
    const raw = withNodes();
    Object.assign(raw.fleetNodes[0], { hostname: 'private-host', ip: '10.0.0.1', execute: true });
    const parsed = validateSnapshot(raw);
    expect(parsed.fleetNodes).toHaveLength(4);
    expect(parsed.fleetNodes![0]).not.toHaveProperty('hostname');
    expect(parsed.fleetNodes![0]).not.toHaveProperty('execute');
    expect(parsed.activity.events[0].nodeId).toBeNull();
  });
  it.each(['duplicate', 'unknown', 'oversized', 'name', 'wing', 'profile', 'assignment', 'evidence', 'observation', 'source', 'source-count'])('rejects malformed fleet roster: %s', kind => {
    const raw = withNodes();
    switch (kind) {
      case 'duplicate': raw.fleetNodes[1] = raw.fleetNodes[0]; break;
      case 'unknown': Object.assign(raw.fleetNodes[0], { id: 'other' }); break;
      case 'oversized': raw.fleetNodes.push(raw.fleetNodes[0]); break;
      case 'name': Object.assign(raw.fleetNodes[0], { name: 'Some private host' }); break;
      case 'wing': raw.fleetNodes[0].wing = 'design'; break;
      case 'profile': Object.assign(raw.fleetNodes[0], { profileId: 'node-other' }); break;
      case 'assignment': raw.fleetNodes[0].assignment = 'configured'; break;
      case 'evidence': raw.fleetNodes[0].evidence = 'local'; break;
      case 'observation': Object.assign(raw.fleetNodes[0], { observedAt: '2026-10-08T12:00:00Z' }); break;
      case 'source': raw.fleetNodes[0].sources = ['/private/device.yaml']; break;
      case 'source-count': raw.fleetNodes[0].sources = Array(5).fill('catalog/fleet-topology.json'); break;
    }
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
  });
  it('accepts verified private assignments with null observation and relative refs', () => {
    const raw = withNodes(); raw.scope.mode = 'local-private';
    raw.fleetNodes.forEach(node => {
      node.assignment = node.id === 'mac-coding-2' ? 'planned' : 'configured';
      node.evidence = node.id === 'mac-coding-2' ? 'pending' : 'local';
      if (node.assignment === 'configured') node.sources.push('fleet.yaml', `nodes/${node.wing}/node.yaml`);
    });
    expect(validateSnapshot(raw).fleetNodes!.filter(n => n.assignment === 'configured')).toHaveLength(3);
  });
  it('allows only the matching canonical per-island profile reference in private scope', () => {
    const raw = withNodes(); raw.scope.mode = 'local-private';
    raw.fleetNodes.forEach(node => {
      node.assignment = 'configured'; node.evidence = 'local';
      node.sources = ['catalog/fleet-topology.json', 'fleet.yaml', `nodes/islands/${node.id}/node.yaml`];
    });
    expect(validateSnapshot(raw).fleetNodes![1].assignment).toBe('configured');
    raw.fleetNodes[1].sources = ['nodes/islands/mac-coding-1/node.yaml'];
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
    raw.fleetNodes[1].sources = ['nodes/islands/../../private/node.yaml'];
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
  });
  it('public templates cannot expose private island profile refs', () => {
    const raw = withNodes(); raw.fleetNodes[1].sources = ['nodes/islands/mac-coding-2/node.yaml'];
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
  });
  it('preserves canonical node activity, rejects host aliases and unknown ids in transport', () => {
    const raw = withNodes(); raw.activity.events[0].nodeId = 'mac-coding-1';
    expect(validateSnapshot(raw).activity.events[0].nodeId).toBe('mac-coding-1');
    raw.activity.events[0].nodeId = 'private-host';
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
  });
});

describe('Ops Contracts and Client', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
  });

  it('validates a correct snapshot schema and strips unknown root and capability fields', () => {
    const rawWithExtras = {
      ...structuredClone(VALID_SNAPSHOT_FIXTURE),
      unexpectedRootField: 'should-be-removed',
      capabilities: {
        documents: true,
        planPreview: true,
        execute: false,
        enable: false,
        approve: false,
        dangerousExtra: true,
      },
    };

    const validated = validateSnapshot(rawWithExtras);
    expect(validated.schema).toBe('snowgloves.cockpit.v1');
    expect(validated.capabilities.documents).toBe(true);
    expect(validated.capabilities.execute).toBe(false);
    expect((validated as unknown as Record<string, unknown>).unexpectedRootField).toBeUndefined();
    expect((validated.capabilities as Record<string, unknown>).dangerousExtra).toBeUndefined();
  });

  it('rejects nested wrong count, invalid status, and unsafe capability flags', () => {
    const invalidCount = structuredClone(VALID_SNAPSHOT_FIXTURE);
    invalidCount.tenants[0].approvalCounts.pending = -1;
    expect(() => validateSnapshot(invalidCount)).toThrow(OpsClientError);

    const invalidStatus = structuredClone(VALID_SNAPSHOT_FIXTURE);
    // @ts-expect-error test invalid status
    invalidStatus.acceptance[0].status = 'invalid-status';
    expect(() => validateSnapshot(invalidStatus)).toThrow(OpsClientError);

    const unsafeCapabilities = structuredClone(VALID_SNAPSHOT_FIXTURE);
    // @ts-expect-error test unsafe execute capability
    unsafeCapabilities.capabilities.execute = true;
    expect(() => validateSnapshot(unsafeCapabilities)).toThrow(OpsClientError);

    const unsafeScopeReadOnly = structuredClone(VALID_SNAPSHOT_FIXTURE);
    // @ts-expect-error test non-readonly scope
    unsafeScopeReadOnly.scope.readOnly = false;
    expect(() => validateSnapshot(unsafeScopeReadOnly)).toThrow(OpsClientError);
  });

  it('rejects unsafe keys in deep safe records', () => {
    const maliciousProfile = structuredClone(VALID_SNAPSHOT_FIXTURE);
    maliciousProfile.fleet[0].profile = JSON.parse('{"__proto__": {"admin": true}}');
    expect(() => validateSnapshot(maliciousProfile)).toThrow(OpsClientError);
  });

  it('loadSnapshot enforces tenant binding matching server response scope', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => VALID_SNAPSHOT_FIXTURE,
    });

    const result = await loadSnapshot('tenant-a');
    expect(result.scope.tenant).toBe('tenant-a');

    await expect(loadSnapshot('tenant-mismatch')).rejects.toThrow(OpsClientError);
  });

  it('fails with HTTP error code on 403 without retry or fallback', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ error: 'Forbidden' }),
    });
    globalThis.fetch = fetchMock;

    await expect(loadSnapshot()).rejects.toMatchObject({
      code: 'http',
      status: 403,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('handles malformed JSON with invalid-response code', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => {
        throw new Error('Unexpected token in JSON');
      },
    });

    await expect(loadSnapshot()).rejects.toMatchObject({
      code: 'invalid-response',
    });
  });

  it('enforces total deadline even if fetch or json resolution delays', async () => {
    vi.useFakeTimers();

    let fetchSignal: AbortSignal | undefined;
    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      fetchSignal = init?.signal;
      return new Promise((resolve) => {
        // Delayed resolution
        setTimeout(() => {
          resolve({
            ok: true,
            json: async () => VALID_SNAPSHOT_FIXTURE,
          });
        }, 15000);
      });
    });

    const loadPromise = loadSnapshot(undefined, { timeoutMs: 3000 });
    const catchSpy = vi.fn();
    loadPromise.catch(catchSpy);

    expect(fetchSignal?.aborted).toBe(false);

    vi.advanceTimersByTime(3001);

    await expect(loadPromise).rejects.toMatchObject({
      code: 'timeout',
    });
    expect(fetchSignal?.aborted).toBe(true);
    expect(catchSpy).toHaveBeenCalled();
  });

  it('enforces deadline if json parsing delays past deadline', async () => {
    vi.useFakeTimers();

    let fetchSignal: AbortSignal | undefined;
    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      fetchSignal = init?.signal;
      return Promise.resolve({
        ok: true,
        json: () =>
          new Promise((resolve) => {
            setTimeout(() => resolve(VALID_SNAPSHOT_FIXTURE), 10000);
          }),
      });
    });

    const loadPromise = loadSnapshot(undefined, { timeoutMs: 2000 });
    const catchSpy = vi.fn();
    loadPromise.catch(catchSpy);

    vi.advanceTimersByTime(2001);

    await expect(loadPromise).rejects.toMatchObject({
      code: 'timeout',
    });
    expect(fetchSignal?.aborted).toBe(true);
  });

  it('handles external pre-aborted and in-flight abort signals', async () => {
    const preController = new AbortController();
    preController.abort();

    await expect(loadSnapshot(undefined, { signal: preController.signal })).rejects.toMatchObject({
      code: 'aborted',
    });

    const inFlightController = new AbortController();
    let capturedSignal: AbortSignal | undefined;
    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      capturedSignal = init?.signal;
      return new Promise((_, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const err = new Error('AbortError');
          err.name = 'AbortError';
          reject(err);
        });
      });
    });

    const flightPromise = loadSnapshot(undefined, { signal: inFlightController.signal });
    const catchSpy = vi.fn();
    flightPromise.catch(catchSpy);

    inFlightController.abort();

    await expect(flightPromise).rejects.toMatchObject({
      code: 'aborted',
    });
    expect(capturedSignal?.aborted).toBe(true);
  });

  it('rejects path traversal attempts before making any fetch request', async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock;

    await expect(loadDocument('../secrets.txt')).rejects.toMatchObject({
      code: 'invalid-path',
    });
    await expect(loadDocument('/etc/passwd')).rejects.toMatchObject({
      code: 'invalid-path',
    });
    await expect(loadDocument('docs\\windows.txt')).rejects.toMatchObject({
      code: 'invalid-path',
    });
    await expect(loadDocument('docs/\0/bad.txt')).rejects.toMatchObject({
      code: 'invalid-path',
    });
    await expect(loadDocument('https://attacker.com/doc.md')).rejects.toMatchObject({
      code: 'invalid-path',
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('validates returned ops document path and sha256', async () => {
    const validDoc = {
      path: 'docs/intro.md',
      content: 'Hello World',
      truncated: false,
      sha256: 'a'.repeat(64),
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => validDoc,
    });

    const doc = await loadDocument('docs/intro.md');
    expect(doc.path).toBe('docs/intro.md');
    expect(doc.sha256).toBe('a'.repeat(64));

    // Mismatched returned path
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...validDoc, path: 'docs/other.md' }),
    });
    await expect(loadDocument('docs/intro.md')).rejects.toMatchObject({
      code: 'invalid-response',
    });

    // Invalid SHA length
    expect(() =>
      validateDocument({
        ...validDoc,
        sha256: 'abc123',
      })
    ).toThrow(OpsClientError);
  });

  it('cleans, canonicalizes, and trims plan preview request before POST', async () => {
    let capturedBody: string | undefined;
    let capturedHeaders: Record<string, string> | undefined;

    const planResponse: PlanPreview = {
      schema: 'snowgloves.cockpit.plan.v1',
      id: 'plan-123',
      tenant: 'tenant-1',
      title: 'Valid Plan Title',
      generatedAt: '2025-01-15T12:00:00Z',
      routes: [{ agent: 'agent-1', hook: 'hook-1', skills: ['skill-a'], source: 'src' }],
      modules: [
        { id: 'mod-1', decision: 'allowed', reason: 'ok' },
        { id: 'mod-2', decision: 'disabled', reason: 'policy' },
        { id: 'mod-3', decision: 'refused', reason: 'security' },
      ],
      steps: [{ id: 'step-1', label: 'Step 1', status: 'proposed', reason: 'init' }],
      executable: false,
      warnings: [],
    };

    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      capturedBody = init?.body as string;
      capturedHeaders = init?.headers as Record<string, string>;
      return Promise.resolve({
        ok: true,
        json: async () => planResponse,
      });
    });

    const request: PlanRequest & { extraIgnoredField?: string } = {
      tenant: 'tenant-1',
      title: '   Valid Plan Title   ',
      modules: ['mod-1', 'mod-2', 'mod-1', 'mod-3'],
      runtime: ' node20 ',
      wing: ' north ',
      extraIgnoredField: 'strip-me',
    };

    const result = await previewPlan(request);
    expect(result.id).toBe('plan-123');
    expect(result.executable).toBe(false);
    expect(capturedHeaders?.['Content-Type']).toBe('application/json');

    const parsedBody = JSON.parse(capturedBody ?? '{}');
    expect(parsedBody).toEqual({
      tenant: 'tenant-1',
      title: 'Valid Plan Title',
      modules: ['mod-1', 'mod-2', 'mod-3'],
      runtime: 'node20',
      wing: 'north',
    });
    expect(parsedBody.extraIgnoredField).toBeUndefined();
  });

  it('denies plan preview with executable: true or mismatched metadata', () => {
    const badPlan = {
      schema: 'snowgloves.cockpit.plan.v1',
      id: 'plan-1',
      tenant: 'tenant-1',
      title: 'Title',
      generatedAt: '2025-01-15T12:00:00Z',
      routes: [],
      modules: [],
      steps: [],
      executable: true,
      warnings: [],
    };

    expect(() => validatePlanPreview(badPlan)).toThrow(OpsClientError);
  });
});

describe('catalog parity and cancellation isolation', () => {
  it('accepts every real public catalog row with its original snake_case fields', async () => {
    const fsModule = 'node:fs';
    const fs = await import(fsModule);
    const catalog = JSON.parse(fs.readFileSync(new URL('../../../catalog/modules.json', import.meta.url), 'utf8'));
    const snapshot = validateSnapshot({ ...VALID_SNAPSHOT_FIXTURE, catalog });
    expect(snapshot.catalog.cards).toHaveLength(137);
    expect(snapshot.catalog.agents).toHaveLength(7);
    expect(snapshot.catalog.adapters).toHaveLength(9);
    expect(snapshot.catalog.connectors).toHaveLength(8);
    expect(snapshot.catalog.agents[0].skill_count).toBe(catalog.agents[0].skill_count);
    expect(snapshot.catalog.adapters.find(a => a.id === 'codex')?.verify).toEqual(catalog.adapters.find((a: {id: string}) => a.id === 'codex').verify);
    expect(snapshot.catalog.connectors.find(c => c.id === 'gmail')?.note).toBeUndefined();
  });

  it('aborts immediately even when fetch ignores its signal and rejects late success', async () => {
    vi.useFakeTimers();
    const external = new AbortController();
    let finish: (value: unknown) => void = () => {};
    const fetchMock = vi.fn().mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    globalThis.fetch = fetchMock;
    const pending = loadSnapshot(undefined, { signal: external.signal, timeoutMs: 8000 });
    const rejected = expect(pending).rejects.toMatchObject({code: 'aborted'});
    external.abort();
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
    finish({ok: true, json: async () => VALID_SNAPSHOT_FIXTURE});
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('aborts a hanging response body without accepting a subsequently completed document', async () => {
    vi.useFakeTimers();
    const external = new AbortController();
    let finish: (value: unknown) => void = () => {};
    globalThis.fetch = vi.fn().mockResolvedValue({ok: true, json: () => new Promise(resolve => { finish = resolve; })});
    const pending = loadDocument('docs/adapters.md', {signal: external.signal});
    const rejected = expect(pending).rejects.toMatchObject({code: 'aborted'});
    await Promise.resolve();
    external.abort();
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
    finish({path: 'docs/adapters.md', content: 'late', truncated: false, sha256: 'a'.repeat(64)});
    await Promise.resolve();
  });

  it('keeps server-selected private scope explicit when no tenant was requested', async () => {
    const raw = structuredClone(VALID_SNAPSHOT_FIXTURE);
    raw.scope.mode = 'local-private';
    raw.scope.tenant = null;
    globalThis.fetch = vi.fn().mockResolvedValue({ok: true, json: async () => raw});
    const snapshot = await loadSnapshot();
    expect(snapshot.scope).toEqual({mode: 'local-private', tenant: null, readOnly: true});
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });

  it('rejects non-JSON and unsafe nested profile values', () => {
    const raw = structuredClone(VALID_SNAPSHOT_FIXTURE);
    raw.fleet[0].profile = {nonJson: new Date()};
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
    raw.fleet[0].profile = JSON.parse('{"__proto__":{"polluted":true}}');
    expect(() => validateSnapshot(raw)).toThrow(OpsClientError);
    expect(({} as {polluted?: boolean}).polluted).toBeUndefined();
  });

  it('allows measured fractional endpoint latency without implying provider readiness', () => {
    const raw = structuredClone(VALID_SNAPSHOT_FIXTURE);
    raw.services[0].latencyMs = 12.345;
    const service = validateSnapshot(raw).services[0];
    expect(service.latencyMs).toBe(12.345);
    expect(service.scope).toBe('endpoint-only');
  });

  it('does not reflect arbitrary network error details', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('sensitive response body')); 
    const error = await loadSnapshot().catch(e => e);
    expect(error).toMatchObject({code: 'network'});
    expect(error.message).not.toContain('sensitive');
  });
});
