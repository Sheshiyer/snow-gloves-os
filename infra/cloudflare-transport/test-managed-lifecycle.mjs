import assert from 'node:assert/strict';
import test from 'node:test';
import { ContainerLifecycleManager, checkManagedReady } from './lifecycle.ts';

const validDigestImage = 'registry.local/omniroute/backend@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
const validEnv = {
  MANAGEMENT_KEY: 'mgmt-key-secret-minimum24chars-fixed',
  BACKEND_API_KEY: 'back-key-secret-minimum24chars-fixed',
  STORAGE_ENCRYPTION_KEY: 'stor-key-secret-minimum24chars-fixed',
  SG_BACKUP_KEY: btoa('12345678901234567890123456789012'),
  SG_BACKUP_KEY_ID: 'key-id-01',
  GATEWAY_INSTANCE_ID: 'inst-01',
  GATEWAY_START_ALLOWED: 'true',
  GATEWAY_PROVIDER_EGRESS: '["api.provider.example"]',
};

function makeStream(str) { return new Response(str).body; }

test('rejects malformed or opaque image reference', async () => {
  const mgr = new ContainerLifecycleManager();
  const cases = ['latest', 'repo:v1', 'sha256:0123456789abcdef', 'repo@sha256:short'];
  for (const img of cases) {
    await assert.rejects(() => mgr.ensureReady({ images: { base: img } }, validEnv), /INVALID_CONTAINER_IMAGE/);
  }
});

test('rejects start hold, invalid backup key and role key collisions', async () => {
  const mgr = new ContainerLifecycleManager();
  const c = { images: { base: validDigestImage } };
  await assert.rejects(() => mgr.ensureReady(c, { ...validEnv, GATEWAY_START_ALLOWED: 'false' }), /GATEWAY_START_HOLD/);
  await assert.rejects(() => mgr.ensureReady(c, { ...validEnv, SG_BACKUP_KEY: 'not-base64!' }), /INVALID_SG_BACKUP_KEY/);
  await assert.rejects(() => mgr.ensureReady(c, { ...validEnv, SG_BACKUP_KEY_ID: 'INVALID_ID$' }), /INVALID_SG_BACKUP_KEY_ID/);
  await assert.rejects(() => mgr.ensureReady(c, { ...validEnv, MANAGEMENT_KEY: validEnv.BACKEND_API_KEY }), /ROLE_KEY_COLLISION/);
  await assert.rejects(() => mgr.ensureReady(c, { ...validEnv, GATEWAY_INITIALIZE_FRESH: 'invalid' }), /INVALID_INITIALIZE_POLICY/);
});

test('full exact env injected without logging and correct port 8080', async () => {
  const mgr = new ContainerLifecycleManager();
  let startOpts = null;
  let portRequested = null;
  const container = {
    images: { base: validDigestImage },
    running: false,
    start(opts) { startOpts = opts; this.running = true; },
    inspect: async () => ({ image: validDigestImage }),
    getTcpPort(p) {
      portRequested = p;
      return { fetch: async () => new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'application/json' } }) };
    },
  };
  const res = await mgr.ensureReady(container, { ...validEnv, GATEWAY_INITIALIZE_FRESH: '1' });
  assert.ok(res);
  assert.equal(portRequested, 8080);
  assert.equal(startOpts.enableInternet, false);
  assert.equal(startOpts.instance, 'standard-1');
  assert.deepEqual(startOpts.env, {
    SG_MANAGEMENT_KEY: validEnv.MANAGEMENT_KEY,
    SG_BACKEND_KEY: validEnv.BACKEND_API_KEY,
    STORAGE_ENCRYPTION_KEY: validEnv.STORAGE_ENCRYPTION_KEY,
    SG_BACKUP_KEY: validEnv.SG_BACKUP_KEY,
    SG_BACKUP_KEY_ID: validEnv.SG_BACKUP_KEY_ID,
    SG_INSTANCE_ID: validEnv.GATEWAY_INSTANCE_ID,
    DATA_DIR: '/data',
    SG_INITIALIZE_FRESH: '1',
    SG_IMAGE_DIGEST: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
  });
});

test('authenticated checkManagedReady validation & bounds', async () => {
  let receivedAuth = '';
  const port = {
    fetch: async (_, init) => {
      receivedAuth = init?.headers?.Authorization;
      return new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'application/json' } });
    },
  };
  assert.equal(await checkManagedReady(port, 'mgmt-secret', 100), true);
  assert.equal(receivedAuth, 'Bearer mgmt-secret');

  const badJsonPort = { fetch: async () => new Response('{"ready":false}', { status: 200, headers: { 'content-type': 'application/json' } }) };
  assert.equal(await checkManagedReady(badJsonPort, 'mgmt-secret', 100), false);

  const nonJsonPort = { fetch: async () => new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'text/plain' } }) };
  assert.equal(await checkManagedReady(nonJsonPort, 'mgmt-secret', 100), false);
});

test('unowned running container or inspect mismatch held', async () => {
  const mgr = new ContainerLifecycleManager();
  const unowned = {
    images: { base: validDigestImage },
    running: true,
    inspect: async () => ({ image: validDigestImage }),
    getTcpPort: () => ({ fetch: async () => new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'application/json' } }) }),
  };
  await assert.rejects(() => mgr.ensureReady(unowned, validEnv), /UNOWNED_OR_DRIFTED_RUNNING_CONTAINER/);

  const mismatchMgr = new ContainerLifecycleManager();
  const mismatchContainer = {
    images: { base: validDigestImage },
    running: false,
    start() { this.running = true; },
    inspect: async () => ({ image: 'wrong-image@sha256:1111111111111111111111111111111111111111111111111111111111111111' }),
    getTcpPort: () => ({ fetch: async () => new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'application/json' } }) }),
  };
  await assert.rejects(() => mismatchMgr.ensureReady(mismatchContainer, validEnv), /CONTAINER_IMAGE_MISMATCH/);
});

test('concurrency single start, cancellation isolation and drift denial', async () => {
  const mgr = new ContainerLifecycleManager();
  let starts = 0;
  const container = {
    images: { base: validDigestImage },
    running: false,
    start() { starts++; this.running = true; },
    inspect: async () => ({ image: validDigestImage }),
    getTcpPort: () => ({
      fetch: async () => {
        await new Promise((r) => setTimeout(r, 50));
        return new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'application/json' } });
      },
    }),
  };
  const ac = new AbortController();
  const p1 = mgr.ensureReady(container, validEnv, ac.signal);
  const p2 = mgr.ensureReady(container, validEnv);
  ac.abort();
  await assert.rejects(() => p1, /ABORTED/);
  const res = await p2;
  assert.ok(res);
  assert.equal(starts, 1);

  await assert.rejects(() => mgr.ensureReady(container, { ...validEnv, MANAGEMENT_KEY: 'n'.repeat(32) }), /UNOWNED_OR_DRIFTED_RUNNING_CONTAINER/);
});
