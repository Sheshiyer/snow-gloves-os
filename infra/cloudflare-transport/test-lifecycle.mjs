import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ContainerLifecycleManager,
  checkPortHealth,
  checkManagedReady,
  readLimitedBody,
  LIFECYCLE_OVERALL_TIMEOUT_MS,
  LIFECYCLE_HEALTH_TIMEOUT_MS,
  LIFECYCLE_MAX_ATTEMPTS,
  validateProviderEgress
} from './lifecycle.ts';
import { readFileSync } from 'node:fs';

function makeStream(chunks, delayMs = 0) {
  return new ReadableStream({
    async start(controller) {
      for (const chunk of chunks) {
        if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
        controller.enqueue(typeof chunk === 'string' ? new TextEncoder().encode(chunk) : chunk);
      }
      controller.close();
    }
  });
}

const validPinnedImage = 'registry.example/owned/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

const validEnv = {
  MANAGEMENT_KEY: 'm'.repeat(32),
  BACKEND_API_KEY: 'b'.repeat(32),
  STORAGE_ENCRYPTION_KEY: 's'.repeat(32),
  SG_BACKUP_KEY: btoa('k'.repeat(32)),
  SG_BACKUP_KEY_ID: 'backup-key-01',
  GATEWAY_INSTANCE_ID: 'instance-01',
  GATEWAY_START_ALLOWED: 'true',
  GATEWAY_PROVIDER_EGRESS: '["api.provider.example"]'
};

test('preconditions: missing container, hold gate, short key, missing image', async () => {
  const mgr = new ContainerLifecycleManager();
  await assert.rejects(() => mgr.ensureReady(undefined, validEnv), /CONTAINER_UNAVAILABLE/);
  await assert.rejects(() => mgr.ensureReady({ images: { base: validPinnedImage } }, { ...validEnv, GATEWAY_START_ALLOWED: 'false' }), /GATEWAY_START_HOLD/);
  await assert.rejects(() => mgr.ensureReady({ images: { base: validPinnedImage } }, { ...validEnv, STORAGE_ENCRYPTION_KEY: 'short' }), /INVALID_STORAGE_ENCRYPTION_KEY/);
  await assert.rejects(() => mgr.ensureReady({}, validEnv), /INVALID_CONTAINER_IMAGE/);
});

test('start gate fails closed without an explicit provider egress allowlist and never opens internet', async () => {
  for (const egress of [undefined, '', '[]']) {
    let starts = 0;
    const container = { images: { base: validPinnedImage }, running: false, start: () => { starts++; } };
    const env = { ...validEnv };
    if (egress === undefined) delete env.GATEWAY_PROVIDER_EGRESS; else env.GATEWAY_PROVIDER_EGRESS = egress;
    await assert.rejects(() => new ContainerLifecycleManager().ensureReady(container, env), /PROVIDER_EGRESS_HOLD/);
    assert.equal(starts, 0);
  }
  for (const egress of ['api.provider.example', '["*"]', '["https://api.provider.example"]', '["a.example","a.example"]', '[1]', '{}']) {
    await assert.rejects(() => new ContainerLifecycleManager().ensureReady({ images: { base: validPinnedImage } },
      { ...validEnv, GATEWAY_PROVIDER_EGRESS: egress }), /INVALID_PROVIDER_EGRESS/);
  }
  assert.deepEqual(validateProviderEgress('["api.provider.example"]'), ['api.provider.example']);
  const config = readFileSync(new URL('./wrangler.jsonc', import.meta.url), 'utf8');
  assert.match(config, /"GATEWAY_PROVIDER_EGRESS": "\[\]"/);
  assert.match(config, /"enable_request_signal"/);
  assert.doesNotMatch(readFileSync(new URL('./lifecycle.ts', import.meta.url), 'utf8'), /enableInternet:\s*true/);
});

test('overrides validation: malicious values rejected', async () => {
  const mgr = new ContainerLifecycleManager();
  const container = {
    images: { base: validPinnedImage },
    running: true,
    inspect: async () => ({ image: validPinnedImage }),
    getTcpPort: () => ({
      fetch: async () => ({
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        body: makeStream(['{"ready":true}'])
      })
    })
  };
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: -1 }), /INVALID_OVERRIDE/);
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 60000 }), /INVALID_OVERRIDE/);
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { maxAttempts: 0 }), /INVALID_OVERRIDE/);
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { maxAttempts: 99 }), /INVALID_OVERRIDE/);
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { healthTimeoutMs: 1.5 }), /INVALID_OVERRIDE/);
});

test('start options accurate and single start call on concurrent invocations', async () => {
  const mgr = new ContainerLifecycleManager();
  const startCalls = [];
  let isRunning = false;
  const container = {
    images: { base: validPinnedImage },
    get running() { return isRunning; },
    inspect: async () => ({ image: validPinnedImage }),
    start(opts) {
      startCalls.push(opts);
      isRunning = true;
    },
    getTcpPort: (p) => ({
      fetch: async (url, init) => {
        assert.equal(init?.headers?.Authorization, `Bearer ${validEnv.MANAGEMENT_KEY}`);
        return {
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          body: makeStream(['{"ready":true}'])
        };
      }
    })
  };

  const [res1, res2] = await Promise.all([
    mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 1000, healthTimeoutMs: 200, maxAttempts: 3 }),
    mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 1000, healthTimeoutMs: 200, maxAttempts: 3 })
  ]);
  assert.equal(startCalls.length, 1);
  assert.deepEqual(startCalls[0], {
    image: validPinnedImage,
    env: {
      SG_MANAGEMENT_KEY: validEnv.MANAGEMENT_KEY,
      SG_BACKEND_KEY: validEnv.BACKEND_API_KEY,
      STORAGE_ENCRYPTION_KEY: validEnv.STORAGE_ENCRYPTION_KEY,
      SG_BACKUP_KEY: validEnv.SG_BACKUP_KEY,
      SG_BACKUP_KEY_ID: validEnv.SG_BACKUP_KEY_ID,
      SG_INSTANCE_ID: validEnv.GATEWAY_INSTANCE_ID,
      DATA_DIR: '/data',
      SG_IMAGE_DIGEST: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    },
    enableInternet: false,
    instance: 'standard-1'
  });
  assert.ok(res1 && res2);
});

test('already running fastpath reprobes and rejects wrong/oversized health or stale cache', async () => {
  const mgr = new ContainerLifecycleManager();
  let probeCount = 0;
  let isRunning = false;
  let currentResponse = { status: 200, headers: new Headers({ 'content-type': 'application/json' }), body: makeStream(['{"ready":true}']) };
  const container = {
    images: { base: validPinnedImage },
    get running() { return isRunning; },
    inspect: async () => ({ image: validPinnedImage }),
    start: () => { isRunning = true; },
    getTcpPort: () => ({
      fetch: async () => {
        probeCount++;
        return currentResponse;
      }
    })
  };

  const initialPort = await mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 1000, healthTimeoutMs: 100, maxAttempts: 3 });
  assert.ok(initialPort);
  assert.equal(probeCount, 1);

  currentResponse = { status: 200, headers: new Headers({ 'content-type': 'application/json' }), body: makeStream(['wrong']) };
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 200, healthTimeoutMs: 50, maxAttempts: 1 }), /RUNNING_CONTAINER_NOT_READY/);
  assert.equal(probeCount, 2);
});

test('oversized body read reject <= 16 bytes', async () => {
  const stream = makeStream(['a'.repeat(17)]);
  await assert.rejects(() => readLimitedBody(stream, 16, 500), /OVERSIZED_HEALTH_BODY/);
});

test('already aborted signal rejects immediately without starting', async () => {
  const mgr = new ContainerLifecycleManager();
  let started = false;
  const container = {
    images: { base: validPinnedImage },
    running: false,
    inspect: async () => ({ image: validPinnedImage }),
    start: () => { started = true; },
    getTcpPort: () => ({
      fetch: async () => ({
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        body: makeStream(['{"ready":true}'])
      })
    })
  };
  const ac = new AbortController();
  ac.abort();
  await assert.rejects(() => mgr.ensureReady(container, validEnv, ac.signal), /ABORTED/);
  assert.equal(started, false);
});

test('cancellation of one waiter does not poison or abort others', async () => {
  const mgr = new ContainerLifecycleManager();
  let fetchCount = 0;
  let isRunning = false;
  const container = {
    images: { base: validPinnedImage },
    get running() { return isRunning; },
    inspect: async () => ({ image: validPinnedImage }),
    start: () => { isRunning = true; },
    getTcpPort: () => ({
      fetch: async () => {
        fetchCount++;
        if (fetchCount < 2) {
          await new Promise((r) => setTimeout(r, 100));
          return { status: 503, headers: new Headers({ 'content-type': 'application/json' }), body: makeStream(['bad']) };
        }
        return { status: 200, headers: new Headers({ 'content-type': 'application/json' }), body: makeStream(['{"ready":true}'])
        };
      }
    })
  };

  const ac1 = new AbortController();
  const p1 = mgr.ensureReady(container, validEnv, ac1.signal, { overallTimeoutMs: 1000, healthTimeoutMs: 200, maxAttempts: 4 });
  const p2 = mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 1000, healthTimeoutMs: 200, maxAttempts: 4 });

  setTimeout(() => ac1.abort(), 30);
  await assert.rejects(() => p1, /ABORTED/);
  const res2 = await p2;
  assert.ok(res2);
});

test('never-resolving fetch is bounded by timeout even if ignoring abort', async () => {
  const neverPort = {
    fetch: () => new Promise(() => {})
  };
  const start = Date.now();
  const healthy = await checkPortHealth(neverPort, 100);
  const duration = Date.now() - start;
  assert.equal(healthy, false);
  assert.ok(duration >= 90 && duration < 300, `Took ${duration}ms`);
});

test('health body never finish is bounded by deadline and releases reader', async () => {
  const stallStream = new ReadableStream({
    start() {}
  });
  const port = {
    fetch: async () => ({ status: 200, body: stallStream })
  };
  const start = Date.now();
  const healthy = await checkPortHealth(port, 100);
  const duration = Date.now() - start;
  assert.equal(healthy, false);
  assert.ok(duration >= 90 && duration < 300);
});

test('listener cleanup on signal after successful resolve and aborted resolve', async () => {
  const mgr = new ContainerLifecycleManager();
  let isRunning = false;
  const container = {
    images: { base: validPinnedImage },
    get running() { return isRunning; },
    inspect: async () => ({ image: validPinnedImage }),
    start: () => { isRunning = true; },
    getTcpPort: () => ({
      fetch: async () => ({
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        body: makeStream(['{"ready":true}'])
      })
    })
  };
  const ac = new AbortController();
  const port = await mgr.ensureReady(container, validEnv, ac.signal, { overallTimeoutMs: 500, healthTimeoutMs: 100, maxAttempts: 2 });
  assert.ok(port);
});
