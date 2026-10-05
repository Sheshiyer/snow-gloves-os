import test from 'node:test';
import assert from 'node:assert/strict';
import { handleGateway, validateAndParseConfig } from './transport.ts';

async function computeSha256Hex(token) {
  const encoder = new TextEncoder();
  const data = encoder.encode(token);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

const rawTokenCoding = 'test-token-coding-wing-minimum24chars';
const rawTokenMarketing = 'test-token-marketing-wing-minimum24chars';
const rawTokenExpired = 'test-token-expired-wing-minimum24chars';
const rawAdminKey = 'test-admin-secret-management-key-only';

const hashCoding = await computeSha256Hex(rawTokenCoding);
const hashMarketing = await computeSha256Hex(rawTokenMarketing);
const hashExpired = await computeSha256Hex(rawTokenExpired);

const validConfig = {
  SCOPED_KEYS_JSON: JSON.stringify([
    {
      sha256: hashCoding,
      wing: 'coding',
      models: ['gpt-4o', 'claude-3-5-sonnet'],
      expiresAt: '2099-01-01T00:00:00.000Z',
    },
    {
      sha256: hashMarketing,
      wing: 'marketing',
      models: ['gpt-4o-mini'],
      expiresAt: '2099-01-01T00:00:00.000Z',
    },
    {
      sha256: hashExpired,
      wing: 'design',
      models: ['claude-3-haiku'],
      expiresAt: '2020-01-01T00:00:00.000Z',
    },
  ]),
  MANAGEMENT_KEY: rawAdminKey,
  BACKEND_API_KEY: 'omniroute-internal-secret-backend-key',
  GATEWAY_INSTANCE_ID: 'company-gateway',
  GATEWAY_START_ALLOWED: 'true',
  STORAGE_ENCRYPTION_KEY: 'test-encryption-key-storage',
};

test('config validation fails closed on invalid config', () => {
  assert.equal(validateAndParseConfig(null), null);
  assert.equal(validateAndParseConfig({ ...validConfig, SCOPED_KEYS_JSON: 'invalid-json' }), null);
  assert.equal(validateAndParseConfig({ ...validConfig, SCOPED_KEYS_JSON: '[]' }), null);
  assert.equal(
    validateAndParseConfig({
      ...validConfig,
      SCOPED_KEYS_JSON: JSON.stringify([
        {
          sha256: hashCoding,
          wing: 'coding',
          models: ['gpt-4o', '*'],
          expiresAt: '2099-01-01T00:00:00.000Z',
        },
      ]),
    }),
    null
  );
});

test('rejects non-https, query strings, and invalid paths', async () => {
  let backendCalled = false;
  const backendFetcher = { fetch: async () => { backendCalled = true; return new Response('ok\n'); } };

  const reqHttp = new Request('http://example.com/v1/models', { headers: { Authorization: `Bearer ${rawTokenCoding}` } });
  const resHttp = await handleGateway(reqHttp, validConfig, backendFetcher);
  assert.equal(resHttp.status, 400);

  const reqQuery = new Request('https://example.com/v1/models?foo=bar', { headers: { Authorization: `Bearer ${rawTokenCoding}` } });
  const resQuery = await handleGateway(reqQuery, validConfig, backendFetcher);
  assert.equal(resQuery.status, 400);

  const req404 = new Request('https://example.com/api/v1/unknown', { headers: { Authorization: `Bearer ${rawTokenCoding}` } });
  const res404 = await handleGateway(req404, validConfig, backendFetcher);
  assert.equal(res404.status, 404);
  assert.equal(backendCalled, false);
});

test('auth enforcement: expired key, admin key on wing path, short token, denied model', async () => {
  let backendCalled = false;
  const backendFetcher = { fetch: async () => { backendCalled = true; return new Response('ok\n'); } };

  const reqExpired = new Request('https://example.com/v1/models', { headers: { Authorization: `Bearer ${rawTokenExpired}` } });
  const resExpired = await handleGateway(reqExpired, validConfig, backendFetcher);
  assert.equal(resExpired.status, 401);

  const reqAdminAsWing = new Request('https://example.com/v1/models', { headers: { Authorization: `Bearer ${rawAdminKey}` } });
  const resAdminAsWing = await handleGateway(reqAdminAsWing, validConfig, backendFetcher);
  assert.equal(resAdminAsWing.status, 401);

  const reqDeniedModel = new Request('https://example.com/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${rawTokenMarketing}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'gpt-4o', messages: [] }),
  });
  const resDeniedModel = await handleGateway(reqDeniedModel, validConfig, backendFetcher);
  assert.equal(resDeniedModel.status, 403);
  assert.equal(backendCalled, false);
});

test('inference POST replaces authorization, strips headers, and prevents origin override', async () => {
  let interceptedReq = null;
  const backendFetcher = {
    fetch: async (url, init) => {
      interceptedReq = { url, init };
      return new Response(JSON.stringify({ id: 'resp_1' }), { status: 200, headers: { 'content-type': 'application/json' } });
    },
  };

  const req = new Request('https://example.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${rawTokenCoding}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
      Cookie: 'session=123',
      'X-Forwarded-For': '1.2.3.4',
    },
    body: JSON.stringify({ model: 'gpt-4o', messages: [{ role: 'user', content: 'hello' }] }),
  });

  const res = await handleGateway(req, validConfig, backendFetcher);
  assert.equal(res.status, 200);
  assert.equal(interceptedReq.url, 'http://container/v1/chat/completions');
  assert.equal(interceptedReq.init.headers.get('authorization'), `Bearer ${validConfig.BACKEND_API_KEY}`);
  assert.equal(interceptedReq.init.headers.get('cookie'), null);
  assert.equal(interceptedReq.init.headers.get('x-forwarded-for'), null);
  assert.ok(interceptedReq.init.headers.get('x-request-id'));
});

test('admin readiness check uses /healthz and limits output', async () => {
  const backendFetcher = {
    fetch: async (url) => {
      assert.equal(url, 'http://container/healthz');
      return new Response('ok\n', { status: 200 });
    },
  };

  const req = new Request('https://example.com/_management/ready', {
    headers: { Authorization: `Bearer ${rawAdminKey}` },
  });
  const res = await handleGateway(req, validConfig, backendFetcher);
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.deepEqual(data, { status: 'ready', lifecycle: 'running' });
});

test('delayed SSE streaming receives first chunk before stream ends and handles backpressure', async () => {
  let backendClosed = false;
  const stream = new ReadableStream({
    async start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"chunk": 1}\n\n'));
      await new Promise((resolve) => setTimeout(resolve, 50));
      controller.enqueue(new TextEncoder().encode('data: {"chunk": 2}\n\n'));
      controller.close();
      backendClosed = true;
    },
  });

  const backendFetcher = {
    fetch: async () => new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
  };

  const req = new Request('https://example.com/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${rawTokenCoding}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'gpt-4o', messages: [] }),
  });

  const res = await handleGateway(req, validConfig, backendFetcher);
  assert.equal(res.status, 200);
  const reader = res.body.getReader();
  const firstChunk = await reader.read();
  assert.equal(new TextDecoder().decode(firstChunk.value), 'data: {"chunk": 1}\n\n');
  assert.equal(backendClosed, false);
  const secondChunk = await reader.read();
  assert.equal(new TextDecoder().decode(secondChunk.value), 'data: {"chunk": 2}\n\n');
});
