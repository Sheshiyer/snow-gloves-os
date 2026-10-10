const FLEET_ID = '[a-f0-9]{32}';
const MAX_FLEET_PROXY_BODY_BYTES = 32 * 1024;

export interface FleetProxyRequest {
  method?: string;
  url?: string;
  headers: Record<string, string | string[] | undefined>;
}

/** Transport-only allowlist for the Vite same-origin fleet route. */
export function fleetProxyAllowed(method: string | undefined, url: string | undefined,
                                  contentLength: string | string[] | undefined): boolean {
  if (!method || !url || url.includes('?') || url.includes('#') || Array.isArray(contentLength)) return false;
  const task = new RegExp(`^/api/fleet/tasks/${FLEET_ID}`);
  const get = url === '/api/fleet/tasks'
    || task.test(url) && new RegExp(`^/api/fleet/tasks/${FLEET_ID}(?:/events)?$`).test(url);
  const post = url === '/api/fleet/tasks'
    || task.test(url) && new RegExp(`^/api/fleet/tasks/${FLEET_ID}/(?:cancel|fanout)$`).test(url);
  if (method === 'GET') return get && (contentLength === undefined || contentLength === '0');
  if (method !== 'POST' || !post || typeof contentLength !== 'string' || !/^(?:0|[1-9]\d*)$/.test(contentLength)) return false;
  const bytes = Number(contentLength);
  return Number.isSafeInteger(bytes) && bytes > 0 && bytes <= MAX_FLEET_PROXY_BODY_BYTES;
}

export function fleetProxyOptions(target = 'http://127.0.0.1:4101') {
  return {
    target,
    changeOrigin: true,
    timeout: 105_000,
    proxyTimeout: 105_000,
    // This is a transport allowlist, not an authorization decision. The
    // coordinator still receives the browser's bearer/origin headers and
    // independently checks owner, permission, capability and body shape.
    bypass: (request: FleetProxyRequest) =>
      fleetProxyAllowed(request.method, request.url, request.headers['content-length']) ? undefined : false,
    rewrite: (path: string) => path.replace(/^\/api\/fleet/, '/v1'),
  };
}
