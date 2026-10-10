import {afterEach, describe, expect, it} from 'vitest';
// @ts-expect-error The browser tsconfig intentionally does not include Node
// declarations; Vitest/Vite supplies this runtime-only test module.
import {createServer as createHttpServer} from 'node:http';
import {createServer as createViteServer} from 'vite';

import {fleetProxyAllowed, fleetProxyOptions} from './fleet-proxy';

const taskId = 'a'.repeat(32);
interface ListeningServer {
  close(callback: () => void): unknown;
  once(name: string, callback: (error: unknown) => void): unknown;
  listen(port: number, host: string, callback: () => void): unknown;
  address(): unknown;
}
interface ViteTestServer {
  close(): Promise<void>;
  listen(): Promise<unknown>;
  httpServer?: {address(): unknown};
}
let upstream: ListeningServer | undefined;
let cockpit: ViteTestServer | undefined;

function portOf(address: unknown, label: string): number {
  if (!address || typeof address !== 'object' || Array.isArray(address)
      || !('port' in address) || typeof address.port !== 'number') {
    throw new Error(`No ${label} address.`);
  }
  return address.port;
}

function listen(server: ListeningServer): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      try { resolve(portOf(server.address(), 'test server')); } catch (error) { reject(error); }
    });
  });
}

afterEach(async () => {
  await cockpit?.close();
  cockpit = undefined;
  await new Promise<void>(resolve => upstream?.close(() => resolve()) ?? resolve());
  upstream = undefined;
});

describe('same-origin fleet proxy allowlist', () => {
  it('allows only the existing task operations plus bounded fanout POST', () => {
    // Planning may use the coordinator's full 90-second Hermes bridge window.
    expect(fleetProxyOptions().proxyTimeout).toBeGreaterThan(90_000);
    expect(fleetProxyOptions().timeout).toBeGreaterThan(90_000);
    const fanout = `/api/fleet/tasks/${taskId}/fanout`;
    expect(fleetProxyAllowed('GET', '/api/fleet/tasks', undefined)).toBe(true);
    expect(fleetProxyAllowed('GET', `/api/fleet/tasks/${taskId}`, '0')).toBe(true);
    expect(fleetProxyAllowed('GET', `/api/fleet/tasks/${taskId}/events`, undefined)).toBe(true);
    expect(fleetProxyAllowed('POST', '/api/fleet/tasks', '24')).toBe(true);
    expect(fleetProxyAllowed('POST', `/api/fleet/tasks/${taskId}/cancel`, '2')).toBe(true);
    expect(fleetProxyAllowed('POST', fanout, '2')).toBe(true);
    expect(fleetProxyAllowed('GET', fanout, undefined)).toBe(false);
    expect(fleetProxyAllowed('POST', `${fanout}?scope=all`, '2')).toBe(false);
    expect(fleetProxyAllowed('POST', '/api/fleet/tasks/not-an-id/fanout', '2')).toBe(false);
    expect(fleetProxyAllowed('POST', fanout, String(32 * 1024 + 1))).toBe(false);
  });

  it('allows only exact catalog, approval, context and artifact routes with bounded bodies', () => {
    for (const path of ['/context', '/capabilities', '/approvals', `/tasks/${taskId}/artifact`]) {
      expect(fleetProxyAllowed('GET', `/api/fleet${path}`, undefined)).toBe(true);
      expect(fleetProxyAllowed('GET', `/api/fleet${path}?tenant=all`, undefined)).toBe(false);
    }
    for (const path of ['/capabilities/execute', '/approvals', `/approvals/${taskId}/approve`, `/approvals/${taskId}/reject`]) {
      expect(fleetProxyAllowed('POST', `/api/fleet${path}`, '2')).toBe(true);
      expect(fleetProxyAllowed('POST', `/api/fleet${path}`, '0')).toBe(false);
      expect(fleetProxyAllowed('POST', `/api/fleet${path}`, String(32 * 1024 + 1))).toBe(false);
    }
    for (const path of ['/workers', '/admin', '/capabilities/enable', `/approvals/${taskId}/delete`, '/approvals/%2e%2e/approve']) {
      expect(fleetProxyAllowed('POST', `/api/fleet${path}`, '2')).toBe(false);
    }
    expect(fleetProxyOptions().bypass({method: 'POST', url: '/api/fleet/approvals', headers: {'content-length': '2', 'transfer-encoding': 'chunked'}})).toBe(false);
  });

  it('forwards approved operations through the real proxy and blocks denied paths before transport', async () => {
    const received: {path: string; body: string; authorization?: string; origin?: string}[] = [];
    upstream = createHttpServer((request: {url?: string; headers: Record<string, string | undefined>; setEncoding(encoding: string): void; on(name: string, callback: (part?: string) => void): void}, response: {setHeader(name: string, value: string): void; end(body: string): void}) => {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (part?: string) => { body += part || ''; });
      request.on('end', () => {
        received.push({
          path: request.url || '',
          body,
          authorization: request.headers.authorization,
          origin: request.headers.origin,
        });
        response.setHeader('Content-Type', 'application/json');
        response.end(JSON.stringify({ok: true}));
      });
    }) as unknown as ListeningServer;
    const upstreamPort = await listen(upstream);
    cockpit = await createViteServer({
      configFile: false,
      root: new URL('..', import.meta.url).pathname,
      appType: 'custom',
      server: {
        host: '127.0.0.1',
        port: 0,
        strictPort: true,
        proxy: {'/api/fleet': fleetProxyOptions(`http://127.0.0.1:${upstreamPort}`)},
      },
    }) as unknown as ViteTestServer;
    await cockpit.listen();
    const base = `http://127.0.0.1:${portOf(cockpit.httpServer?.address(), 'cockpit proxy')}`;
    const headers = {Authorization: 'Bearer operator-token', Origin: 'http://127.0.0.1:18760'};
    const request = (method: string, path: string, body?: string) => fetch(base + path, {
      method,
      headers: {...headers, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      ...(body === undefined ? {} : {body}),
    });

    for (const [method, path, body] of [
      ['GET', '/api/fleet/tasks', undefined],
      ['GET', `/api/fleet/tasks/${taskId}`, undefined],
      ['GET', `/api/fleet/tasks/${taskId}/events`, undefined],
      ['POST', '/api/fleet/tasks', '{"project":"snowgloves"}'],
      ['POST', `/api/fleet/tasks/${taskId}/cancel`, '{}'],
      ['POST', `/api/fleet/tasks/${taskId}/fanout`, '{}'],
      ['GET', '/api/fleet/context', undefined],
      ['GET', '/api/fleet/capabilities', undefined],
      ['GET', '/api/fleet/approvals', undefined],
      ['GET', `/api/fleet/tasks/${taskId}/artifact`, undefined],
      ['POST', '/api/fleet/capabilities/execute', '{"project":"snowgloves"}'],
      ['POST', '/api/fleet/approvals', '{"project":"snowgloves"}'],
      ['POST', `/api/fleet/approvals/${taskId}/approve`, '{}'],
      ['POST', `/api/fleet/approvals/${taskId}/reject`, '{}'],
    ] as const) {
      expect((await request(method, path, body)).status).toBe(200);
    }
    expect(received.map(item => item.path)).toEqual([
      '/v1/tasks',
      `/v1/tasks/${taskId}`,
      `/v1/tasks/${taskId}/events`,
      '/v1/tasks',
      `/v1/tasks/${taskId}/cancel`,
      `/v1/tasks/${taskId}/fanout`,
      '/v1/context', '/v1/capabilities', '/v1/approvals', `/v1/tasks/${taskId}/artifact`,
      '/v1/capabilities/execute', '/v1/approvals', `/v1/approvals/${taskId}/approve`, `/v1/approvals/${taskId}/reject`,
    ]);
    expect(received.every(item => item.authorization === headers.Authorization && item.origin === headers.Origin)).toBe(true);
    expect(received.at(-1)?.body).toBe('{}');

    const forwarded = received.length;
    expect((await fetch(`${base}/api/fleet/approvals`, {method: 'POST', headers: {...headers, 'Content-Type': 'text/plain'}, body: '{}'})).status).toBe(404);
    expect((await request('GET', `/api/fleet/tasks/${taskId}/fanout`)).status).toBe(404);
    expect((await request('POST', `/api/fleet/tasks/${taskId}/fanout`, 'x'.repeat(32 * 1024 + 1))).status).toBe(404);
    expect((await request('POST', '/api/fleet/tasks/admin/fanout', '{}')).status).toBe(404);
    expect(received).toHaveLength(forwarded);
  });
});
