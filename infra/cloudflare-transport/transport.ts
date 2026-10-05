import { checkManagedReady } from './lifecycle.ts';

export interface ScopedKeyEntry {
  sha256: string;
  wing: 'coding' | 'marketing' | 'design';
  models: string[];
  expiresAt: string;
}

export interface GatewayConfig {
  SCOPED_KEYS_JSON: string;
  MANAGEMENT_KEY: string;
  BACKEND_API_KEY: string;
  GATEWAY_INSTANCE_ID: string;
  GATEWAY_START_ALLOWED: string;
  STORAGE_ENCRYPTION_KEY: string;
}

export interface BackendFetcher {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

export interface ValidatedKey {
  wing: 'coding' | 'marketing' | 'design';
  models: Set<string>;
  expiresAtMs: number;
}

export interface ParsedConfig {
  scopedKeys: Map<string, ValidatedKey>;
  backendApiKey: string;
  instanceId: string;
  startAllowed: boolean;
  storageEncryptionKey: string;
}

export interface AuthorizeResult {
  response?: Response;
  authorized?: {
    kind: 'management' | 'models' | 'inference';
    matchedKey?: ValidatedKey;
    parsedConfig: ParsedConfig;
    rawBody?: Uint8Array;
    jsonBody?: Record<string, unknown>;
  };
}

export const REDACTED_503 = () =>
  new Response(JSON.stringify({ error: 'service_unavailable' }), {
    status: 503,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

export const JSON_ERROR = (status: number, message: string) =>
  new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

export const REDACTED_502 = () =>
  new Response(JSON.stringify({ error: 'bad_gateway' }), {
    status: 502,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

const ALLOWED_WINGS = new Set(['coding', 'marketing', 'design']);
const FORBIDDEN_BODY_FIELDS = new Set([
  'provider',
  'providerId',
  'provider_id',
  'base_url',
  'baseUrl',
  'api_key',
  'apiKey',
  'endpoint',
  'url',
]);

const HEX_REGEX = /^[0-9a-f]{64}$/;
const INSTANCE_ID_REGEX = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ISO_UTC_REGEX = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;
const SCOPED_KEY_KNOWN_FIELDS = new Set(['sha256', 'wing', 'models', 'expiresAt']);

export const MAX_INFERENCE_BODY_BYTES = 1048576; // 1 MB
export const MAX_ADMIN_HEALTH_BYTES = 16;
export const INFERENCE_BODY_TIMEOUT_MS = 5000;
export const ADMIN_READY_TIMEOUT_MS = 3000;

export function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export async function sha256Hex(token: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(token);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

export function validateAndParseConfig(config: GatewayConfig): ParsedConfig | null {
  if (
    !config ||
    typeof config.SCOPED_KEYS_JSON !== 'string' ||
    typeof config.MANAGEMENT_KEY !== 'string' ||
    typeof config.BACKEND_API_KEY !== 'string' ||
    typeof config.GATEWAY_INSTANCE_ID !== 'string' ||
    typeof config.GATEWAY_START_ALLOWED !== 'string' ||
    typeof config.STORAGE_ENCRYPTION_KEY !== 'string'
  ) {
    return null;
  }

  if (
    config.SCOPED_KEYS_JSON.length === 0 ||
    config.SCOPED_KEYS_JSON.length > 65536 ||
    config.MANAGEMENT_KEY.length < 24 ||
    config.MANAGEMENT_KEY.length > 4096 ||
    config.BACKEND_API_KEY.length < 24 ||
    config.BACKEND_API_KEY.length > 4096 ||
    config.STORAGE_ENCRYPTION_KEY.length < 24 ||
    config.STORAGE_ENCRYPTION_KEY.length > 4096 ||
    !INSTANCE_ID_REGEX.test(config.GATEWAY_INSTANCE_ID)
  ) {
    return null;
  }

  let parsedKeysRaw: unknown;
  try {
    parsedKeysRaw = JSON.parse(config.SCOPED_KEYS_JSON);
  } catch {
    return null;
  }

  if (!Array.isArray(parsedKeysRaw) || parsedKeysRaw.length === 0 || parsedKeysRaw.length > 64) {
    return null;
  }

  const scopedKeys = new Map<string, ValidatedKey>();

  for (const item of parsedKeysRaw) {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) {
      return null;
    }
    const entry = item as Record<string, unknown>;
    const entryKeys = Object.keys(entry);
    for (const k of entryKeys) {
      if (!SCOPED_KEY_KNOWN_FIELDS.has(k)) {
        return null;
      }
    }

    if (
      typeof entry.sha256 !== 'string' ||
      !HEX_REGEX.test(entry.sha256) ||
      typeof entry.wing !== 'string' ||
      !ALLOWED_WINGS.has(entry.wing) ||
      !Array.isArray(entry.models) ||
      entry.models.length === 0 ||
      typeof entry.expiresAt !== 'string' ||
      !ISO_UTC_REGEX.test(entry.expiresAt)
    ) {
      return null;
    }

    if (scopedKeys.has(entry.sha256)) {
      return null;
    }

    const expiresAtMs = Date.parse(entry.expiresAt);
    const canonicalExpiry = entry.expiresAt.replace(/(?:\.(\d{1,3}))?Z$/, (_, fraction: string | undefined) => '.' + (fraction ?? '').padEnd(3, '0') + 'Z');
    if (Number.isNaN(expiresAtMs) || new Date(expiresAtMs).toISOString() !== canonicalExpiry) {
      return null;
    }

    const modelSet = new Set<string>();
    for (const m of entry.models) {
      if (typeof m !== 'string' || m.length === 0 || m.includes('*') || modelSet.has(m)) {
        return null;
      }
      modelSet.add(m);
    }

    scopedKeys.set(entry.sha256, {
      wing: entry.wing as 'coding' | 'marketing' | 'design',
      models: modelSet,
      expiresAtMs,
    });
  }

  return {
    scopedKeys,
    backendApiKey: config.BACKEND_API_KEY,
    instanceId: config.GATEWAY_INSTANCE_ID,
    startAllowed: config.GATEWAY_START_ALLOWED === 'true',
    storageEncryptionKey: config.STORAGE_ENCRYPTION_KEY,
  };
}

export async function readLimitedBody(
  body: ReadableStream<Uint8Array> | null,
  maxBytes: number,
  deadlineMs: number,
  signal?: AbortSignal
): Promise<Uint8Array> {
  if (signal?.aborted) {
    throw new Error('ABORTED');
  }
  if (!body) {
    return new Uint8Array(0);
  }

  const reader = body.getReader();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let abortListener: (() => void) | null = null;

  try {
    const cancelPromise = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        reject(new Error('TIMEOUT'));
      }, deadlineMs);

      if (signal) {
        abortListener = () => reject(new Error('ABORTED'));
        signal.addEventListener('abort', abortListener, { once: true });
      }
    });

    const chunks: Uint8Array[] = [];
    let totalBytes = 0;

    const readLoop = async (): Promise<Uint8Array> => {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        if (value) {
          totalBytes += value.byteLength;
          if (totalBytes > maxBytes) {
            throw new Error('PAYLOAD_TOO_LARGE');
          }
          chunks.push(value);
        }
      }
      const combined = new Uint8Array(totalBytes);
      let offset = 0;
      for (const chunk of chunks) {
        combined.set(chunk, offset);
        offset += chunk.byteLength;
      }
      return combined;
    };

    return await Promise.race([readLoop(), cancelPromise]);
  } catch (err) {
    try {
      reader.cancel(err).catch(() => {});
    } catch {}
    throw err;
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
    if (signal && abortListener) {
      signal.removeEventListener('abort', abortListener);
    }
    try {
      reader.releaseLock();
    } catch {}
  }
}

export async function authorizeGateway(
  request: Request,
  config: GatewayConfig,
  overrides?: { inferenceMaxBytes?: number; inferenceDeadlineMs?: number }
): Promise<AuthorizeResult> {
  if (overrides && Object.entries(overrides).some(([name, value]) => !Number.isInteger(value) || value <= 0 || value > (name === 'inferenceMaxBytes' ? MAX_INFERENCE_BODY_BYTES : INFERENCE_BODY_TIMEOUT_MS))) {
    return { response: REDACTED_503() };
  }
  const parsedConfig = validateAndParseConfig(config);
  if (!parsedConfig) {
    return { response: REDACTED_503() };
  }

  let url: URL;
  try {
    url = new URL(request.url);
  } catch {
    return { response: JSON_ERROR(400, 'invalid_url') };
  }

  if (url.protocol !== 'https:') {
    return { response: JSON_ERROR(400, 'https_required') };
  }

  if (url.search && url.search.length > 0) {
    return { response: JSON_ERROR(400, 'query_strings_forbidden') };
  }

  const rawPath = url.pathname;
  if (rawPath.includes('%')) {
    return { response: JSON_ERROR(400, 'invalid_url') };
  }

  const authHeader = request.headers.get('authorization');

  if (rawPath === '/_management/ready') {
    if (request.method !== 'GET') {
      return { response: JSON_ERROR(405, 'method_not_allowed') };
    }
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return { response: JSON_ERROR(401, 'unauthorized') };
    }
    const token = authHeader.slice(7).trim();
    if (token.length === 0) {
      return { response: JSON_ERROR(401, 'unauthorized') };
    }
    const tokenDigest = await sha256Hex(token);
    const expectedAdminDigest = await sha256Hex(config.MANAGEMENT_KEY);
    if (!constantTimeEqual(tokenDigest, expectedAdminDigest)) {
      return { response: JSON_ERROR(401, 'unauthorized') };
    }

    if (!parsedConfig.startAllowed) return { response: REDACTED_503() };
    return {
      authorized: {
        kind: 'management',
        parsedConfig,
      },
    };
  }

  if (
    rawPath !== '/v1/models' &&
    rawPath !== '/v1/chat/completions' &&
    rawPath !== '/v1/responses'
  )
  {
    return { response: JSON_ERROR(404, 'not_found') };
  }

  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return { response: JSON_ERROR(401, 'unauthorized') };
  }
  const token = authHeader.slice(7).trim();
  if (token.length < 24 || token.length > 256) {
    return { response: JSON_ERROR(401, 'unauthorized') };
  }

  const adminDigest = await sha256Hex(config.MANAGEMENT_KEY);
  const tokenDigest = await sha256Hex(token);
  if (constantTimeEqual(tokenDigest, adminDigest)) {
    return { response: JSON_ERROR(401, 'unauthorized') };
  }

  let matchedKey: ValidatedKey | null = null;
  for (const [digestHex, keyEntry] of parsedConfig.scopedKeys.entries()) {
    if (constantTimeEqual(tokenDigest, digestHex)) {
      matchedKey = keyEntry;
      break;
    }
  }

  if (!matchedKey) {
    return { response: JSON_ERROR(401, 'unauthorized') };
  }

  if (Date.now() >= matchedKey.expiresAtMs) {
    return { response: JSON_ERROR(401, 'key_expired') };
  }

  if (rawPath === '/v1/models') {
    if (request.method !== 'GET') {
      return { response: JSON_ERROR(405, 'method_not_allowed') };
    }
    return {
      authorized: {
        kind: 'models',
        matchedKey,
        parsedConfig,
      },
    };
  }

  if (rawPath === '/v1/responses') {
    return { response: REDACTED_503() };
  }

  if (rawPath === '/v1/chat/completions') {
    if (request.method !== 'POST') {
      return { response: JSON_ERROR(405, 'method_not_allowed') };
    }

    const contentType = request.headers.get('content-type') || '';
    const match = contentType.match(/^application\/json(?:;\s*charset=utf-8)?$/i);
    if (!match) {
      return { response: JSON_ERROR(400, 'invalid_content_type') };
    }

    const maxBytes = overrides?.inferenceMaxBytes ?? MAX_INFERENCE_BODY_BYTES;
    const deadlineMs = overrides?.inferenceDeadlineMs ?? INFERENCE_BODY_TIMEOUT_MS;

    let rawBody: Uint8Array;
    try {
      rawBody = await readLimitedBody(request.body, maxBytes, deadlineMs, request.signal);
    } catch (err: unknown) {
      if (err instanceof Error && err.message === 'PAYLOAD_TOO_LARGE') {
        return { response: JSON_ERROR(413, 'payload_too_large') };
      }
      return { response: JSON_ERROR(400, 'body_read_error') };
    }

    let jsonBody: Record<string, unknown>;
    try {
      const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: false }).decode(rawBody);
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return { response: JSON_ERROR(400, 'invalid_json_body') };
      }
      jsonBody = parsed as Record<string, unknown>;
    } catch {
      return { response: JSON_ERROR(400, 'malformed_json') };
    }

    for (const key of Object.keys(jsonBody)) {
      if (FORBIDDEN_BODY_FIELDS.has(key)) {
        return { response: JSON_ERROR(400, 'forbidden_field_in_body') };
      }
    }

    const model = jsonBody.model;
    if (typeof model !== 'string' || !matchedKey.models.has(model)) {
      return { response: JSON_ERROR(403, 'model_not_allowed') };
    }

    if (!parsedConfig.startAllowed) return { response: REDACTED_503() };
    return {
      authorized: {
        kind: 'inference',
        matchedKey,
        parsedConfig,
        rawBody,
        jsonBody,
      },
    };
  }

  return { response: JSON_ERROR(404, 'not_found') };
}

export async function handleGateway(
  request: Request,
  config: GatewayConfig,
  backendFetcher: BackendFetcher,
  overrides?: {
    adminReadyTimeoutMs?: number;
    inferenceMaxBytes?: number;
    inferenceDeadlineMs?: number;
  }
): Promise<Response> {
  if (overrides?.adminReadyTimeoutMs !== undefined && (!Number.isInteger(overrides.adminReadyTimeoutMs) || overrides.adminReadyTimeoutMs <= 0 || overrides.adminReadyTimeoutMs > ADMIN_READY_TIMEOUT_MS)) return REDACTED_503();
  const authResult = await authorizeGateway(request, config, overrides);
  if (authResult.response) {
    return authResult.response;
  }

  const authorized = authResult.authorized;
  if (!authorized) {
    return JSON_ERROR(401, 'unauthorized');
  }

  const url = new URL(request.url);
  const pathname = url.pathname;

  if (authorized.kind === 'management') {
    const timeout = overrides?.adminReadyTimeoutMs ?? ADMIN_READY_TIMEOUT_MS;
    const ready = await checkManagedReady(backendFetcher, config.MANAGEMENT_KEY, timeout, request.signal);
    return ready ? Response.json({ status: 'ready', lifecycle: 'running' }) : JSON_ERROR(503, 'not_ready');
  }

  if (authorized.kind === 'models' && authorized.matchedKey) {
    const matchedKey = authorized.matchedKey;
    const modelList = Array.from(matchedKey.models).map((id) => ({
      id,
      object: 'model',
      created: 1700000000,
      owned_by: matchedKey.wing,
    }));
    return new Response(JSON.stringify({ object: 'list', data: modelList }), {
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }

  if (authorized.kind === 'inference' && authorized.rawBody) {
    const requestId = crypto.randomUUID();
    const upstreamHeaders = new Headers();
    upstreamHeaders.set('authorization', `Bearer ${authorized.parsedConfig.backendApiKey}`);
    upstreamHeaders.set('content-type', 'application/json; charset=utf-8');
    const clientAccept = request.headers.get('accept');
    if (clientAccept) {
      upstreamHeaders.set('accept', clientAccept);
    }
    upstreamHeaders.set('x-request-id', requestId);

    try {
      const upstreamResp = await backendFetcher.fetch(`http://container${pathname}`, {
        method: 'POST',
        headers: upstreamHeaders,
        body: JSON.stringify(authorized.jsonBody),
        signal: request.signal,
      });

      const sanitizedHeaders = new Headers();
      const upstreamContentType = upstreamResp.headers.get('content-type');
      if (upstreamContentType) {
        sanitizedHeaders.set('content-type', upstreamContentType);
      }
      const upstreamCacheControl = upstreamResp.headers.get('cache-control');
      if (upstreamCacheControl) {
        sanitizedHeaders.set('cache-control', upstreamCacheControl);
      }
      sanitizedHeaders.set('x-request-id', requestId);

      return new Response(upstreamResp.body, {
        status: upstreamResp.status,
        headers: sanitizedHeaders,
      });
    } catch {
      return REDACTED_502();
    }
  }

  return JSON_ERROR(404, 'not_found');
}
