import test from 'node:test';
import assert from 'node:assert/strict';
import { checkPortHealth, ContainerLifecycleManager } from './lifecycle.ts';

const validPinnedImage = 'registry.example/owned/runtime@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const validEnv = {
  MANAGEMENT_KEY: 'm'.repeat(32),
  BACKEND_API_KEY: 'b'.repeat(32),
  STORAGE_ENCRYPTION_KEY: 's'.repeat(32),
  SG_BACKUP_KEY: btoa('k'.repeat(32)),
  SG_BACKUP_KEY_ID: 'backup-key-01',
  GATEWAY_INSTANCE_ID: 'instance-01',
  GATEWAY_START_ALLOWED: 'true'
};

test('completed health probe leaves no live timer', async () => {
  const before = process.getActiveResourcesInfo().filter((x) => x === 'Timeout').length;
  assert.equal(await checkPortHealth({ fetch: async () => new Response('ok\n') }, 100), true);
  assert.equal(process.getActiveResourcesInfo().filter((x) => x === 'Timeout').length, before);
});

test('cancellation interrupts an already-running unresponsive health probe promptly', async () => {
  const abort = new AbortController();
  let isRunning = false;
  let fetchNever = false;
  const container = {
    get running() { return isRunning; },
    images: { base: validPinnedImage },
    inspect: async () => ({ image: validPinnedImage }),
    start() { isRunning = true; },
    getTcpPort() {
      return {
        fetch: async () => {
          if (fetchNever) return new Promise(() => {});
          return new Response('{"ready":true}', { headers: { 'content-type': 'application/json' } });
        }
      };
    }
  };

  const mgr = new ContainerLifecycleManager();
  await mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 500, healthTimeoutMs: 100, maxAttempts: 1 });
  fetchNever = true;

  const start = Date.now();
  const timer = setTimeout(() => abort.abort(), 10);
  try {
    await assert.rejects(
      mgr.ensureReady(container, validEnv, abort.signal, { overallTimeoutMs: 300, healthTimeoutMs: 200, maxAttempts: 1 }),
      /ABORTED/
    );
    assert.ok(Date.now() - start < 100);
  } finally {
    clearTimeout(timer);
  }
});

test('fresh manager rejects unowned running container', async () => {
  const container = {
    running: true,
    images: { base: validPinnedImage },
    inspect: async () => ({ image: validPinnedImage }),
    start() { throw new Error('must not start'); },
    getTcpPort() {
      return { fetch: async () => new Response('{"ready":true}', { headers: { 'content-type': 'application/json' } }) };
    }
  };
  await assert.rejects(
    new ContainerLifecycleManager().ensureReady(container, validEnv, undefined, { overallTimeoutMs: 300, healthTimeoutMs: 50, maxAttempts: 2 }),
    /UNOWNED_OR_DRIFTED_RUNNING_CONTAINER/
  );
});

test('running health fastpath probes once and throws on unhealthy without restart', async () => {
  let probes = 0;
  let isRunning = false;
  let startCalls = 0;
  let currentResponse = new Response('{"ready":true}', { headers: { 'content-type': 'application/json' } });
  const container = {
    get running() { return isRunning; },
    images: { base: validPinnedImage },
    inspect: async () => ({ image: validPinnedImage }),
    start() {
      startCalls++;
      isRunning = true;
    },
    getTcpPort() {
      return {
        fetch: async () => {
          probes++;
          return currentResponse;
        }
      };
    }
  };

  const mgr = new ContainerLifecycleManager();
  await mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 500, healthTimeoutMs: 100, maxAttempts: 1 });
  assert.equal(startCalls, 1);
  assert.equal(probes, 1);

  currentResponse = new Response('wrong', { headers: { 'content-type': 'application/json' } });
  await assert.rejects(
    mgr.ensureReady(container, validEnv, undefined, { overallTimeoutMs: 300, healthTimeoutMs: 50, maxAttempts: 2 }),
    /RUNNING_CONTAINER_NOT_READY/
  );
  assert.equal(probes, 2);
  assert.equal(startCalls, 1);
});
