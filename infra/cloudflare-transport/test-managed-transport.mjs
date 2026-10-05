import test from 'node:test';
import assert from 'node:assert/strict';
import { handleGateway, authorizeGateway, sha256Hex } from './transport.ts';

const M_KEY = 'm-mgmt-secret-key-32bytes-fixed!!';
const B_KEY = 'b-backend-secret-32bytes-fixed!!';
const S_KEY = 's-storage-secret-32bytes-fixed!!';
const C_KEY = 'c-client-synthetic-key-32bytes!';
const C_SHA = await sha256Hex(C_KEY);

const validConfig = {
  SCOPED_KEYS_JSON: JSON.stringify([
    {
      sha256: C_SHA,
      wing: 'coding',
      models: ['model-a', 'model-b'],
      expiresAt: '2099-01-01T00:00:00.000Z',
    },
  ]),
  MANAGEMENT_KEY: M_KEY,
  BACKEND_API_KEY: B_KEY,
  STORAGE_ENCRYPTION_KEY: S_KEY,
  GATEWAY_INSTANCE_ID: 'inst-01',
  GATEWAY_START_ALLOWED: 'true',
};

test('management readiness sends Authorization header and requires exact JSON {"ready":true}', async () => {
  let receivedUrl = null;
  let receivedAuth = null;

  const mockBackend = {
    fetch: async (url, init) => {
      receivedUrl = url;
      receivedAuth = init?.headers?.Authorization || init?.headers?.authorization;
      return new Response('{"ready":true}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  };

  const req = new Request('https://gateway.test/_management/ready', {
    headers: { authorization: `Bearer ${M_KEY}` },
  });
  const res = await handleGateway(req, validConfig, mockBackend);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { status: 'ready', lifecycle: 'running' });
  assert.equal(receivedUrl, 'http://container/_management/ready');
  assert.equal(receivedAuth, `Bearer ${M_KEY}`);
});

test('management readiness rejects raw health, non-json, malformed json, or wrong ready value', async () => {
  const rejectCases = [
    new Response('ok\n', { status: 200, headers: { 'content-type': 'text/plain' } }),
    new Response('ok', { status: 200, headers: { 'content-type': 'text/plain' } }),
    new Response('{"ready":false}', { status: 200, headers: { 'content-type': 'application/json' } }),
    new Response('{"status":"ready"}', { status: 200, headers: { 'content-type': 'application/json' } }),
    new Response('{"ready":true}\n', { status: 200, headers: { 'content-type': 'application/json' } }),
    new Response('{"ready":true}', { status: 200, headers: { 'content-type': 'text/plain' } }),
    new Response('{"ready":true}', { status: 500, headers: { 'content-type': 'application/json' } }),
  ];

  for (const mockResp of rejectCases) {
    const backend = { fetch: async () => mockResp };
    const req = new Request('https://gateway.test/_management/ready', {
      headers: { authorization: `Bearer ${M_KEY}` },
    });
    const res = await handleGateway(req, validConfig, backend);
    assert.equal(res.status, 503);
  }
});

test('management readiness timeout bounded and handles aborted signal', async () => {
  const abortController = new AbortController();
  abortController.abort();

  let backendCalls = 0;
  const backend = {
    fetch: async () => {
      backendCalls++;
      return new Response('{"ready":true}', { headers: { 'content-type': 'application/json' } });
    },
  };

  const reqAborted = new Request('https://gateway.test/_management/ready', {
    headers: { authorization: `Bearer ${M_KEY}` },
    signal: abortController.signal,
  });
  const resAborted = await handleGateway(reqAborted, validConfig, backend);
  assert.equal(resAborted.status, 503);
  assert.equal(backendCalls, 0);

  const slowBackend = {
    fetch: () => new Promise(() => {}),
  };
  const start = Date.now();
  const reqSlow = new Request('https://gateway.test/_management/ready', {
    headers: { authorization: `Bearer ${M_KEY}` },
  });
  const resSlow = await handleGateway(reqSlow, validConfig, slowBackend, { adminReadyTimeoutMs: 30 });
  assert.equal(resSlow.status, 503);
  assert.ok(Date.now() - start < 150);
});

test('/v1/responses holds 503 BEFORE any backend call for valid auth, 401/403 for invalid', async () => {
  let backendCalls = 0;
  const backend = {
    fetch: async () => {
      backendCalls++;
      return new Response('ok');
    },
  };

  const reqValid = new Request('https://gateway.test/v1/responses', {
    method: 'POST',
    headers: { authorization: `Bearer ${C_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'model-a', input: 'test' }),
  });
  const resValid = await handleGateway(reqValid, validConfig, backend);
  assert.equal(resValid.status, 503);
  assert.equal(backendCalls, 0);

  const reqNoAuth = new Request('https://gateway.test/v1/responses', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'model-a' }),
  });
  const resNoAuth = await handleGateway(reqNoAuth, validConfig, backend);
  assert.equal(resNoAuth.status, 401);
  assert.equal(backendCalls, 0);

  const reqMgmtOnResponses = new Request('https://gateway.test/v1/responses', {
    method: 'POST',
    headers: { authorization: `Bearer ${M_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'model-a' }),
  });
  const resMgmt = await handleGateway(reqMgmtOnResponses, validConfig, backend);
  assert.equal(resMgmt.status, 401);
  assert.equal(backendCalls, 0);
});

test('models route succeeds locally when GATEWAY_START_ALLOWED is false', async () => {
  let backendCalls = 0;
  const backend = { fetch: async () => { backendCalls++; return new Response('ok'); } };
  const heldConfig = { ...validConfig, GATEWAY_START_ALLOWED: 'false' };

  const reqModels = new Request('https://gateway.test/v1/models', {
    headers: { authorization: `Bearer ${C_KEY}` },
  });
  const resModels = await handleGateway(reqModels, heldConfig, backend);
  assert.equal(resModels.status, 200);
  const data = await resModels.json();
  assert.deepEqual(data, {
    object: 'list',
    data: [
      { id: 'model-a', object: 'model', created: 1700000000, owned_by: 'coding' },
      { id: 'model-b', object: 'model', created: 1700000000, owned_by: 'coding' },
    ],
  });
  assert.equal(backendCalls, 0);
});
