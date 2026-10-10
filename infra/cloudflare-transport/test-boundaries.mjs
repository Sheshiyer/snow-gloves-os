import test from 'node:test';
import assert from 'node:assert/strict';
import { handleGateway, sha256Hex, readLimitedBody } from './transport.ts';

const deferred = () => { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); p.resolve = res; p.reject = rej; return p; };
const enc = (t) => new TextEncoder().encode(t);
const M_KEY = 'm-mgmt-secret-key-32bytes-fixed!!';
const B_KEY = 'b-backend-secret-32bytes-fixed!!';
const S_KEY = 's-storage-secret-32bytes-fixed!!';
const C_KEY = 'c-client-synthetic-key-32bytes!';
const C_SHA = await sha256Hex(C_KEY);

const baseCfg = (override = {}) => ({
  SCOPED_KEYS_JSON: JSON.stringify([{
    sha256: C_SHA,
    wing: 'coding',
    models: ['model-a', 'model-b'],
    expiresAt: '2099-01-01T00:00:00.000Z',
  }]),
  MANAGEMENT_KEY: M_KEY,
  BACKEND_API_KEY: B_KEY,
  GATEWAY_INSTANCE_ID: 'inst-01',
  GATEWAY_START_ALLOWED: 'true',
  STORAGE_ENCRYPTION_KEY: S_KEY,
  ...override,
});

test('config parsing & scope boundary validation', async () => {
  const badConfigs = [
    { SCOPED_KEYS_JSON: '' },
    { SCOPED_KEYS_JSON: JSON.stringify([]) },
    { SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'unknown', models: ['m'], expiresAt: '2099-01-01T00:00:00.000Z' }]) },
    { SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'coding', models: ['*'], expiresAt: '2099-01-01T00:00:00.000Z' }]) },
    { SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'coding', models: ['m', 'm'], expiresAt: '2099-01-01T00:00:00.000Z' }]) },
    { SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'coding', models: ['m'], expiresAt: '2099-01-01T00:00:00+02:00' }]) },
    { SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'coding', models: ['m'], expiresAt: '2099-01-01T00:00:00.000Z', extra: 1 }]) },
    { SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'coding', models: ['m'], expiresAt: '2099-01-01T00:00:00.000Z' }, { sha256: C_SHA, wing: 'design', models: ['m2'], expiresAt: '2099-01-01T00:00:00.000Z' }]) },
    { MANAGEMENT_KEY: 'short' },
    { BACKEND_API_KEY: 'short' },
    { STORAGE_ENCRYPTION_KEY: 'short' },
    { GATEWAY_INSTANCE_ID: 'INVALID_ID_$' },
  ];

  let backendCalls = 0;
  const fetcher = { fetch: async () => { backendCalls++; return new Response('ok\n'); } };
  for (const cfg of badConfigs) {
    const res = await handleGateway(new Request('https://gateway.test/v1/models', { headers: { authorization: `Bearer ${C_KEY}` } }), baseCfg(cfg), fetcher);
    assert.equal(res.status, 503);
  }
  assert.equal(backendCalls, 0);
});

test('auth & routing boundaries, separation & denied scope never calls backend', async () => {
  let backendCalls = 0;
  const fetcher = { fetch: async () => { backendCalls++; return new Response('ok\n'); } };
  const expiredCfg = baseCfg({
    SCOPED_KEYS_JSON: JSON.stringify([{ sha256: C_SHA, wing: 'coding', models: ['model-a'], expiresAt: '2020-01-01T00:00:00.000Z' }]),
  });

  const cases = [
    { req: new Request('https://gateway.test/v1/models'), status: 401, desc: 'missing auth' },
    { req: new Request('https://gateway.test/v1/models?token=' + C_KEY), status: 400, desc: 'query param forbidden' },
    { req: new Request('https://gateway.test/v1/models', { headers: { cookie: `token=${C_KEY}` } }), status: 401, desc: 'cookie auth ignored' },
    { req: new Request('https://gateway.test/v1/models', { headers: { 'x-api-key': C_KEY } }), status: 401, desc: 'x-api-key header ignored' },
    { req: new Request('https://gateway.test/v1/models', { headers: { authorization: `Bearer ${M_KEY}` } }), status: 401, desc: 'mgmt key on model route' },
    { req: new Request('https://gateway.test/_management/ready', { headers: { authorization: `Bearer ${C_KEY}` } }), status: 401, desc: 'wing key on mgmt route' },
    { req: new Request('https://gateway.test/v1/models', { headers: { authorization: `Bearer ${C_KEY}` } }), cfg: expiredCfg, status: 401, desc: 'exact expired deny' },
    { req: new Request('https://gateway.test/v1%2Fmodels', { headers: { authorization: `Bearer ${C_KEY}` } }), status: 400, desc: 'encoded path 400' },
    { req: new Request('https://gateway.test/v1/models', { method: 'POST', headers: { authorization: `Bearer ${C_KEY}` } }), status: 405, desc: 'GET models wrong method' },
    { req: new Request('https://gateway.test/v1/chat/completions', { method: 'GET', headers: { authorization: `Bearer ${C_KEY}` } }), status: 405, desc: 'POST route wrong method' },
    { req: new Request('https://gateway.test/v1/unknown', { headers: { authorization: `Bearer ${C_KEY}` } }), status: 404, desc: 'not found route' },
  ];

  for (const c of cases) {
    const res = await handleGateway(c.req, c.cfg || baseCfg(), fetcher);
    assert.equal(res.status, c.status, c.desc);
  }
  assert.equal(backendCalls, 0);
});

test('GET /v1/models wing allowed list only', async () => {
  const res = await handleGateway(new Request('https://gateway.test/v1/models', { headers: { authorization: `Bearer ${C_KEY}` } }), baseCfg(), { fetch: async () => assert.fail('should not call') });
  assert.equal(res.status, 200);
  const json = await res.json();
  assert.deepEqual(json, {
    object: 'list',
    data: [
      { id: 'model-a', object: 'model', created: 1700000000, owned_by: 'coding' },
      { id: 'model-b', object: 'model', created: 1700000000, owned_by: 'coding' },
    ],
  });
});

test('inference body validation: content-type, json structure, forbidden overrides, forbidden model', async () => {
  let backendCalls = 0;
  const fetcher = { fetch: async () => { backendCalls++; return new Response('ok'); } };
  const cfg = baseCfg();

  const cases = [
    { headers: { 'content-type': 'text/plain' }, body: '{"model":"model-a"}', status: 400, desc: 'bad content-type' },
    { headers: { 'content-type': 'application/json' }, body: new Uint8Array([0xff, 0xfe, 0x00]), status: 400, desc: 'malformed utf-8' },
    { headers: { 'content-type': 'application/json' }, body: '{invalid-json}', status: 400, desc: 'malformed json' },
    { headers: { 'content-type': 'application/json' }, body: '["model-a"]', status: 400, desc: 'array json body' },
    { headers: { 'content-type': 'application/json' }, body: JSON.stringify({ model: 'model-a', provider: 'openai' }), status: 400, desc: 'forbidden provider field' },
    { headers: { 'content-type': 'application/json' }, body: JSON.stringify({ model: 'model-a', base_url: 'http://foo' }), status: 400, desc: 'forbidden base_url field' },
    { headers: { 'content-type': 'application/json' }, body: JSON.stringify({ model: 'model-c' }), status: 403, desc: 'unauthorized model denial' },
  ];

  for (const c of cases) {
    const req = new Request('https://gateway.test/v1/chat/completions', {
      method: 'POST',
      headers: { authorization: `Bearer ${C_KEY}`, ...c.headers },
      body: c.body,
    });
    const res = await handleGateway(req, cfg, fetcher);
    assert.equal(res.status, c.status, c.desc);
  }
  assert.equal(backendCalls, 0);
});

test('inference forwarding: canonical body, fresh headers, header stripping & error redaction', async () => {
  let capturedReq = null;
  const fetcher = {
    fetch: async (url, init) => {
      capturedReq = { url, init };
      return new Response(JSON.stringify({ ok: true }), {
        status: 201,
        headers: {
          'content-type': 'application/json; charset=utf-8',
          'set-cookie': 'session=bad',
          'location': '/secret-location',
          'x-internal-token': 'leak-token',
        },
      });
    },
  };

  const rawPayload = '{"model":"model-a","model":"model-a","prompt":"hi"}';
  const req = new Request('https://gateway.test/v1/chat/completions', {
    method: 'POST',
    headers: {
      'authorization': `Bearer ${C_KEY}`,
      'content-type': 'application/json',
      'accept': 'application/json, text/event-stream',
      'cookie': 'user=123',
      'x-internal-header': 'spoof',
    },
    body: rawPayload,
  });

  const res = await handleGateway(req, baseCfg(), fetcher);
  assert.equal(res.status, 201);
  assert.equal(capturedReq.url, 'http://container/v1/chat/completions');
  const sentHeaders = capturedReq.init.headers;
  assert.equal(sentHeaders.get('authorization'), `Bearer ${B_KEY}`);
  assert.equal(sentHeaders.get('accept'), 'application/json, text/event-stream');
  assert.equal(sentHeaders.get('cookie'), null);
  assert.equal(sentHeaders.get('x-internal-header'), null);
  assert.equal(typeof sentHeaders.get('x-request-id'), 'string');
  assert.deepEqual(JSON.parse(capturedReq.init.body), { model: 'model-a', prompt: 'hi' });

  assert.equal(res.headers.get('set-cookie'), null);
  assert.equal(res.headers.get('location'), null);
  assert.equal(res.headers.get('x-internal-token'), null);
  assert.equal(res.headers.get('content-type'), 'application/json; charset=utf-8');

  const failFetcher = { fetch: async () => { throw new Error('sensitive upstream database failure details at 10.0.0.1'); } };
  const failReq = new Request('https://gateway.test/v1/chat/completions', {
    method: 'POST',
    headers: { authorization: `Bearer ${C_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'model-a' }),
  });
  const failRes = await handleGateway(failReq, baseCfg(), failFetcher);
  assert.equal(failRes.status, 502);
  const failJson = await failRes.json();
  assert.deepEqual(failJson, { error: 'bad_gateway' });
});

test('readLimitedBody bounds: stream overflow cancelled once, stalls & abort timeouts', async () => {
  let streamCancelled = 0;
  const overStream = new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(10));
      controller.enqueue(new Uint8Array(10));
    },
    cancel() { streamCancelled++; },
  });
  await assert.rejects(readLimitedBody(overStream, 15, 1000), /PAYLOAD_TOO_LARGE/);
  assert.equal(streamCancelled, 1);

  const stallDef = deferred();
  const stallStream = new ReadableStream({
    pull() { return stallDef; },
    cancel() { stallDef.resolve(); },
  });
  await assert.rejects(readLimitedBody(stallStream, 100, 50), /TIMEOUT/);

  const ac = new AbortController();
  ac.abort();
  const emptyStream = new ReadableStream({});
  await assert.rejects(readLimitedBody(emptyStream, 100, 1000, ac.signal), /ABORTED/);
});

test('health endpoint: wrong status, 17-byte overflow, slow read timeout (50ms override)', async () => {
  const cfg = baseCfg();
  const authHeaders = { headers: { authorization: `Bearer ${M_KEY}` } };

  const wrongStatus = await handleGateway(new Request('https://gateway.test/_management/ready', authHeaders), cfg, {
    fetch: async () => new Response('ok\n', { status: 500 }),
  });
  assert.equal(wrongStatus.status, 503);

  const over16Bytes = await handleGateway(new Request('https://gateway.test/_management/ready', authHeaders), cfg, {
    fetch: async () => new Response('12345678901234567', {headers: {'content-type':'application/json'}}),
  });
  assert.equal(over16Bytes.status, 503);

  const slowDef = deferred();
  const slowStream = new ReadableStream({
    pull() { return slowDef; },
    cancel() { slowDef.resolve(); },
  });
  const timeoutRes = await handleGateway(
    new Request('https://gateway.test/_management/ready', authHeaders),
    cfg,
    { fetch: async (_, init) => new Response(slowStream, { status: 200, headers: {'content-type':'application/json'} }) },
    { adminReadyTimeoutMs: 50 }
  );
  assert.equal(timeoutRes.status, 503);
  const readyOk = await handleGateway(new Request('https://gateway.test/_management/ready', authHeaders), cfg, {
    fetch: async () => new Response('{"ready":true}', { status: 200, headers: {'content-type':'application/json'} }),
  });
  assert.equal(readyOk.status, 200);
  assert.deepEqual(await readyOk.json(), { status: 'ready', lifecycle: 'running' });
});

test('streaming SSE: chunk delivery, client cancellation propagates upstream, producer backpressure bounded', async () => {
  let upstreamCancelled = false;
  let pullCount = 0;
  const pullDef = deferred();

  const upstreamStream = new ReadableStream({
    pull(controller) {
      pullCount++;
      if (pullCount === 1) {
        controller.enqueue(enc('data: first chunk\n\n'));
      } else if (pullCount === 2) {
        controller.enqueue(enc('data: second chunk\n\n'));
      } else {
        return pullDef;
      }
    },
    cancel() {
      upstreamCancelled = true;
      pullDef.resolve();
    },
  });

  const fetcher = {
    fetch: async () => new Response(upstreamStream, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    }),
  };

  const res = await handleGateway(new Request('https://gateway.test/v1/chat/completions', {
    method: 'POST',
    headers: { authorization: `Bearer ${C_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'model-a' }),
  }), baseCfg(), fetcher);

  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-type'), 'text/event-stream');

  const reader = res.body.getReader();
  const chunk1 = await reader.read();
  assert.equal(new TextDecoder().decode(chunk1.value), 'data: first chunk\n\n');
  assert.ok(pullCount <= 3, 'backpressure should keep pulls bounded');

  await reader.cancel();
  assert.equal(upstreamCancelled, true, 'upstream stream should be cancelled on consumer cancel');
});
