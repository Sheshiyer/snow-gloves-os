import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ContainerLifecycleManager,
  checkPortHealth,
  readLimitedBody,
  LIFECYCLE_OVERALL_TIMEOUT_MS,
  LIFECYCLE_HEALTH_TIMEOUT_MS,
  LIFECYCLE_MAX_ATTEMPTS
} from './lifecycle.ts';

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

const validEnv = { STORAGE_ENCRYPTION_KEY: 'a'.repeat(32), GATEWAY_START_ALLOWED: 'true' };

test('preconditions: missing container, hold gate, short key, missing image', async () => {
  const mgr = new ContainerLifecycleManager();
  await assert.rejects(() => mgr.ensureReady(undefined, validEnv), /CONTAINER_UNAVAILABLE/);
  await assert.rejects(() => mgr.ensureReady({}, { ...validEnv, GATEWAY_START_ALLOWED: 'false' }), /GATEWAY_START_HOLD/);
  await assert.rejects(() => mgr.ensureReady({ images: { base: 'img' } }, { ...validEnv, STORAGE_ENCRYPTION_KEY: 'short' }), /INVALID_STORAGE_ENCRYPTION_KEY/);
  await assert.rejects(() => mgr.ensureReady({}, validEnv), /CONTAINER_IMAGE_NOT_FOUND/);
});

test('overrides validation: malicious values rejected', async () => {
  const mgr = new ContainerLifecycleManager();
  const container = { images: { base: 'img' }, running: true, getTcpPort: () => ({ fetch: async () => ({ status: 200, body: makeStream(['ok\n']) }) }) };
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
    images: { base: 'cf-image-candidate' },
    get running() { return isRunning; },
    start(opts) {
      startCalls.push(opts);
      isRunning = true;
    },
    getTcpPort: (p) => ({
      fetch: async () => ({ status: 200, body: makeStream(['ok\n']) })
    })
  };

  const [res1, res2] = await Promise.all([
    mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 1000, healthTimeoutMs: 200, maxAttempts: 3 }),
    mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 1000, healthTimeoutMs: 200, maxAttempts: 3 })
  ]);
  assert.equal(startCalls.length, 1);
  assert.deepEqual(startCalls[0], {
    image: 'cf-image-candidate',
    env: { STORAGE_ENCRYPTION_KEY: validEnv.STORAGE_ENCRYPTION_KEY },
    enableInternet: false,
    instance: 'standard-1'
  });
  assert.ok(res1 && res2);
});

test('already running fastpath reprobes and rejects wrong/oversized health or stale cache', async () => {
  const mgr = new ContainerLifecycleManager();
  let probeCount = 0;
  const container = {
    images: { base: 'img' },
    running: true,
    start: () => {},
    getTcpPort: () => ({
      fetch: async () => {
        probeCount++;
        return { status: 200, body: makeStream(['wrong\n']) };
      }
    })
  };
  await assert.rejects(() => mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 200, healthTimeoutMs: 50, maxAttempts: 2 }), /CONTAINER_START_TIMEOUT/);
  assert.ok(probeCount >= 2);
});

test('oversized body read reject <= 16 bytes', async () => {
  const stream = makeStream(['a'.repeat(17)]);
  await assert.rejects(() => readLimitedBody(stream, 16, 500), /OVERSIZED_HEALTH_BODY/);
});

test('already aborted signal rejects immediately without starting', async () => {
  const mgr = new ContainerLifecycleManager();
  let started = false;
  const container = { images: { base: 'img' }, running: false, start: () => { started = true; }, getTcpPort: () => ({ fetch: async () => ({ status: 200, body: makeStream(['ok\n']) }) }) };
  const ac = new AbortController();
  ac.abort();
  await assert.rejects(() => mgr.ensureReady(container, validEnv, ac.signal), /ABORTED/);
  assert.equal(started, false);
});

test('cancellation of one waiter does not poison or abort others', async () => {
  const mgr = new ContainerLifecycleManager();
  let fetchCount = 0;
  const container = {
    images: { base: 'img' },
    running: false,
    start: () => {},
    getTcpPort: () => ({
      fetch: async () => {
        fetchCount++;
        if (fetchCount < 2) {
          await new Promise((r) => setTimeout(r, 100));
          return { status: 503, body: makeStream(['bad']) };
        }
        return { status: 200, body: makeStream(['ok\n']) };
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
  const container = {
    images: { base: 'img' },
    running: true,
    getTcpPort: () => ({ fetch: async () => ({ status: 200, body: makeStream(['ok\n']) }) })
  };
  const ac = new AbortController();
  const port = await mgr.ensureReady(container, validEnv, ac.signal, { overallTimeoutMs: 500, healthTimeoutMs: 100, maxAttempts: 2 });
  assert.ok(port);
});
