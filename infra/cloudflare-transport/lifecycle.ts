export interface LifecycleEnv {
  MANAGEMENT_KEY: string;
  BACKEND_API_KEY: string;
  STORAGE_ENCRYPTION_KEY: string;
  SG_BACKUP_KEY: string;
  SG_BACKUP_KEY_ID: string;
  GATEWAY_INSTANCE_ID: string;
  GATEWAY_START_ALLOWED: string;
  GATEWAY_INITIALIZE_FRESH?: string;
  /** JSON array of provider hostnames the runtime may reach. Unset or `[]` (the default) holds start. */
  GATEWAY_PROVIDER_EGRESS?: string;
}

export const LIFECYCLE_OVERALL_TIMEOUT_MS = 5000;
export const LIFECYCLE_HEALTH_TIMEOUT_MS = 1000;
export const LIFECYCLE_MAX_ATTEMPTS = 5;
export const CONTAINER_PORT = 8080;
export const MAX_ADMIN_HEALTH_BYTES = 16;

const KEY_REGEX = /^[A-Za-z0-9._~-]{32,256}$/;
const BASE64_32_REGEX = /^(?:[A-Za-z0-9+/]{4}){10}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const INSTANCE_ID_REGEX = /^[a-z0-9][a-z0-9-]{0,63}$/;
const KEY_ID_REGEX = /^[a-z0-9][a-z0-9-]{0,63}$/;
const HOSTNAME_REGEX = /^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;
const MAX_PROVIDER_EGRESS_HOSTS = 16;
const DIGEST_PINNED_IMAGE_REGEX = /^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:\/[a-z0-9]+(?:[._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$/;

function validatePositiveFiniteBound(val: number | undefined, maxAllowed: number, defaultVal: number): number {
  if (val === undefined) return defaultVal;
  if (typeof val !== 'number' || !Number.isFinite(val) || val <= 0 || !Number.isInteger(val) || val > maxAllowed) {
    throw new Error('INVALID_OVERRIDE');
  }
  return val;
}

export async function readLimitedBody(
  body: ReadableStream<Uint8Array> | null,
  maxBytes: number,
  deadlineMs: number,
  signal?: AbortSignal
): Promise<Uint8Array> {
  if (!body) return new Uint8Array(0);
  const reader = body.getReader();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;

  const cancelPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reader.cancel().catch(() => {});
      reject(new Error('DEADLINE_EXCEEDED'));
    }, deadlineMs);

    if (signal) {
      if (signal.aborted) {
        reader.cancel().catch(() => {});
        reject(new Error('ABORTED'));
        return;
      }
      onAbort = () => {
        reader.cancel().catch(() => {});
        reject(new Error('ABORTED'));
      };
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });

  const readTask = (async () => {
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          total += value.byteLength;
          if (total > maxBytes) {
            await reader.cancel().catch(() => {});
            throw new Error('OVERSIZED_HEALTH_BODY');
          }
          chunks.push(value);
        }
      }
      const result = new Uint8Array(total);
      let offset = 0;
      for (const c of chunks) {
        result.set(c, offset);
        offset += c.byteLength;
      }
      return result;
    } finally {
      try { reader.releaseLock(); } catch {}
    }
  })();

  try {
    return await Promise.race([readTask, cancelPromise]);
  } finally {
    if (timer) clearTimeout(timer);
    if (signal && onAbort) signal.removeEventListener('abort', onAbort);
  }
}

export async function checkPortHealth(
  port: Pick<Fetcher, 'fetch'>,
  timeoutMs: number = LIFECYCLE_HEALTH_TIMEOUT_MS,
  signal?: AbortSignal
): Promise<boolean> {
  if (signal?.aborted) return false;
  const controller = new AbortController();
  const began = Date.now();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  const stopped = new Promise<boolean>((resolve) => {
    const stop = () => { controller.abort(); resolve(false); };
    timer = setTimeout(stop, timeoutMs);
    if (signal) {
      onAbort = stop;
      signal.addEventListener('abort', onAbort, { once: true });
      if (signal.aborted) stop();
    }
  });
  const probe = (async () => {
    try {
      const response = await port.fetch('http://container/healthz', {
        method: 'GET', signal: controller.signal,
      });
      const remaining = timeoutMs - (Date.now() - began);
      if (controller.signal.aborted || response.status !== 200 || remaining <= 0) {
        void response.body?.cancel().catch(() => {});
        return false;
      }
      const bytes = await readLimitedBody(response.body, MAX_ADMIN_HEALTH_BYTES, remaining, controller.signal);
      return !controller.signal.aborted && new TextDecoder('utf-8', {fatal: true, ignoreBOM: false}).decode(bytes) === 'ok\n';
    } catch { return false; }
  })();
  try { return await Promise.race([probe, stopped]); }
  finally {
    if (timer !== undefined) clearTimeout(timer);
    if (signal && onAbort) signal.removeEventListener('abort', onAbort);
  }
}

export async function checkManagedReady(
  port: Pick<Fetcher, 'fetch'>,
  managementKey: string,
  timeoutMs: number = LIFECYCLE_HEALTH_TIMEOUT_MS,
  signal?: AbortSignal
): Promise<boolean> {
  if (signal?.aborted) return false;
  const controller = new AbortController();
  const began = Date.now();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  const stopped = new Promise<boolean>((resolve) => {
    const stop = () => { controller.abort(); resolve(false); };
    timer = setTimeout(stop, timeoutMs);
    if (signal) {
      onAbort = stop;
      signal.addEventListener('abort', onAbort, { once: true });
      if (signal.aborted) stop();
    }
  });
  const probe = (async () => {
    try {
      const response = await port.fetch('http://container/_management/ready', {
        method: 'GET',
        headers: { Authorization: `Bearer ${managementKey}` },
        signal: controller.signal,
      });
      const remaining = timeoutMs - (Date.now() - began);
      if (controller.signal.aborted || response.status !== 200 || remaining <= 0) {
        void response.body?.cancel().catch(() => {});
        return false;
      }
      const contentType = response.headers.get('content-type') || '';
      if (!/^application\/json(?:\s*;|$)/i.test(contentType)) {
        void response.body?.cancel().catch(() => {});
        return false;
      }
      const bytes = await readLimitedBody(response.body, MAX_ADMIN_HEALTH_BYTES, remaining, controller.signal);
      if (controller.signal.aborted) return false;
      const decoded = new TextDecoder('utf-8', { fatal: true, ignoreBOM: false }).decode(bytes);
      return decoded === '{"ready":true}';
    } catch { return false; }
  })();
  try { return await Promise.race([probe, stopped]); }
  finally {
    if (timer !== undefined) clearTimeout(timer);
    if (signal && onAbort) signal.removeEventListener('abort', onAbort);
  }
}

/**
 * The container starts with `enableInternet: false` and this lane has no outbound interceptor, so a
 * started runtime cannot reach any model provider. Starting therefore requires an explicit provider
 * egress allowlist; without one the start gate fails closed with PROVIDER_EGRESS_HOLD instead of
 * starting a runtime whose provider calls would all fail. Internet access is never opened here.
 */
export function validateProviderEgress(value: string | undefined): string[] {
  if (value === undefined || value === '' || value === '[]') throw new Error('PROVIDER_EGRESS_HOLD');
  let hosts: unknown;
  try { hosts = JSON.parse(value); } catch { throw new Error('INVALID_PROVIDER_EGRESS'); }
  if (!Array.isArray(hosts) || hosts.length === 0 || hosts.length > MAX_PROVIDER_EGRESS_HOSTS
      || !hosts.every((h) => typeof h === 'string' && HOSTNAME_REGEX.test(h))
      || new Set(hosts).size !== hosts.length) {
    throw new Error('INVALID_PROVIDER_EGRESS');
  }
  return hosts as string[];
}

export function validateEnv(env: LifecycleEnv): { imageDigest: string; envToInject: Record<string, string> } {
  if (env.GATEWAY_START_ALLOWED !== 'true') throw new Error('GATEWAY_START_HOLD');
  validateProviderEgress(env.GATEWAY_PROVIDER_EGRESS);
  if (env.GATEWAY_INITIALIZE_FRESH !== undefined && env.GATEWAY_INITIALIZE_FRESH !== '1') throw new Error('INVALID_INITIALIZE_POLICY');

  for (const k of ['MANAGEMENT_KEY', 'BACKEND_API_KEY', 'STORAGE_ENCRYPTION_KEY'] as const) {
    if (typeof env[k] !== 'string' || !KEY_REGEX.test(env[k])) throw new Error(`INVALID_${k}`);
  }

  if (typeof env.SG_BACKUP_KEY !== 'string' || !BASE64_32_REGEX.test(env.SG_BACKUP_KEY)) throw new Error('INVALID_SG_BACKUP_KEY');
  let decodedBackupKey: string;
  try {
    const bin = atob(env.SG_BACKUP_KEY);
    if (bin.length !== 32 || btoa(bin) !== env.SG_BACKUP_KEY) throw new Error();
    decodedBackupKey = bin;
  } catch { throw new Error('INVALID_SG_BACKUP_KEY'); }

  if (typeof env.SG_BACKUP_KEY_ID !== 'string' || !KEY_ID_REGEX.test(env.SG_BACKUP_KEY_ID)) throw new Error('INVALID_SG_BACKUP_KEY_ID');
  if (typeof env.GATEWAY_INSTANCE_ID !== 'string' || !INSTANCE_ID_REGEX.test(env.GATEWAY_INSTANCE_ID)) throw new Error('INVALID_GATEWAY_INSTANCE_ID');

  const roleKeys = [env.MANAGEMENT_KEY, env.BACKEND_API_KEY, env.STORAGE_ENCRYPTION_KEY, env.SG_BACKUP_KEY];
  const distinct = new Set(roleKeys);
  if (distinct.size !== 4 || distinct.has(decodedBackupKey)) throw new Error('ROLE_KEY_COLLISION');

  const envToInject: Record<string, string> = {
    SG_MANAGEMENT_KEY: env.MANAGEMENT_KEY,
    SG_BACKEND_KEY: env.BACKEND_API_KEY,
    STORAGE_ENCRYPTION_KEY: env.STORAGE_ENCRYPTION_KEY,
    SG_BACKUP_KEY: env.SG_BACKUP_KEY,
    SG_BACKUP_KEY_ID: env.SG_BACKUP_KEY_ID,
    SG_INSTANCE_ID: env.GATEWAY_INSTANCE_ID,
    DATA_DIR: '/data',
  };
  if (env.GATEWAY_INITIALIZE_FRESH === '1') {
    envToInject.SG_INITIALIZE_FRESH = '1';
  }
  return { imageDigest: '', envToInject };
}

export class ContainerLifecycleManager {
  private startPromise: Promise<Fetcher> | null = null;
  private activeInstanceConfigHash: string | null = null;
  private pendingConfigHash: string | null = null;
  private ownedContainer: Container | null = null;

  private async computeConfigFingerprint(env: LifecycleEnv, selectedImage: string): Promise<string> {
    const payload = JSON.stringify([env.MANAGEMENT_KEY, env.BACKEND_API_KEY, env.STORAGE_ENCRYPTION_KEY, env.SG_BACKUP_KEY, env.SG_BACKUP_KEY_ID, env.GATEWAY_INSTANCE_ID, env.GATEWAY_INITIALIZE_FRESH ?? null, env.GATEWAY_PROVIDER_EGRESS ?? null, selectedImage]);
    const data = new TextEncoder().encode(payload);
    const hash = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(hash)).map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  private async boundedInspect(container: Container, timeoutMs: number, signal?: AbortSignal): Promise<{ image: string }> {
    if (signal?.aborted) throw new Error('ABORTED');
    if (timeoutMs <= 0) throw new Error('INSPECT_TIMEOUT');
    if (typeof container.inspect !== 'function') throw new Error('INSPECT_UNAVAILABLE');
    let timer: ReturnType<typeof setTimeout> | undefined;
    let onAbort: (() => void) | undefined;
    const inspectPromise = Promise.race([
      container.inspect(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('INSPECT_TIMEOUT')), timeoutMs);
        if (signal) {
          onAbort = () => reject(new Error('ABORTED'));
          signal.addEventListener('abort', onAbort, { once: true });
        }
      })
    ]);
    try {
      const info = await inspectPromise;
      if (signal?.aborted) throw new Error('ABORTED');
      if (!info || typeof info.image !== 'string') throw new Error('INSPECT_UNAVAILABLE');
      return info;
    } finally {
      if (timer) clearTimeout(timer);
      if (signal && onAbort) signal.removeEventListener('abort', onAbort);
    }
  }

  async ensureReady(
    container: Container | undefined,
    env: LifecycleEnv,
    signal?: AbortSignal,
    overrides?: {
      overallTimeoutMs?: number;
      healthTimeoutMs?: number;
      maxAttempts?: number;
    }
  ): Promise<Fetcher> {
    if (signal?.aborted) throw new Error('ABORTED');
    if (!container) throw new Error('CONTAINER_UNAVAILABLE');

    const baseImage = container.images?.base;
    if (!baseImage || typeof baseImage !== 'string' || !DIGEST_PINNED_IMAGE_REGEX.test(baseImage)) {
      throw new Error('INVALID_CONTAINER_IMAGE');
    }
    const derivedDigest = baseImage.slice(baseImage.lastIndexOf('@sha256:') + 8);
    const { envToInject } = validateEnv(env);
    envToInject.SG_IMAGE_DIGEST = derivedDigest;

    const overallTimeout = validatePositiveFiniteBound(overrides?.overallTimeoutMs, LIFECYCLE_OVERALL_TIMEOUT_MS, LIFECYCLE_OVERALL_TIMEOUT_MS);
    const healthTimeout = validatePositiveFiniteBound(overrides?.healthTimeoutMs, LIFECYCLE_HEALTH_TIMEOUT_MS, LIFECYCLE_HEALTH_TIMEOUT_MS);
    const maxAttempts = validatePositiveFiniteBound(overrides?.maxAttempts, LIFECYCLE_MAX_ATTEMPTS, LIFECYCLE_MAX_ATTEMPTS);

    const deadline = Date.now() + overallTimeout;
    const configFingerprint = await this.computeConfigFingerprint(env, baseImage);
    if (signal?.aborted) throw new Error('ABORTED');
    if (Date.now() >= deadline) throw new Error('CONTAINER_START_TIMEOUT');
    if (this.startPromise && (this.pendingConfigHash !== configFingerprint || this.ownedContainer !== container)) throw new Error('START_CONFIG_DRIFT');

    let attemptsUsed = 0;
    if (container.running && !this.startPromise) {
      if (this.activeInstanceConfigHash !== configFingerprint || this.ownedContainer !== container) {
        throw new Error('UNOWNED_OR_DRIFTED_RUNNING_CONTAINER');
      }
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new Error('CONTAINER_START_TIMEOUT');
      const singleHealthBudget = Math.min(healthTimeout, remaining);
      const inspectInfo = await this.boundedInspect(container, singleHealthBudget, signal);
      if (inspectInfo.image !== baseImage) throw new Error('CONTAINER_IMAGE_MISMATCH');
      const port = container.getTcpPort(CONTAINER_PORT);
      attemptsUsed++;
      const readinessBudget = Math.min(healthTimeout, deadline - Date.now());
      if (readinessBudget <= 0) throw new Error('CONTAINER_START_TIMEOUT');
      const isHealthy = await checkManagedReady(port, env.MANAGEMENT_KEY, readinessBudget, signal);
      if (Date.now() >= deadline) throw new Error('CONTAINER_START_TIMEOUT');
      if (signal?.aborted) throw new Error('ABORTED');
      if (isHealthy) return port;
    }

    if (!this.startPromise) {
      if (container.running) throw new Error('RUNNING_CONTAINER_NOT_READY');
      this.pendingConfigHash = configFingerprint;
      this.ownedContainer = container;
      this.activeInstanceConfigHash = null;
      this.startPromise = (async () => {
        if (!container.running) {
          container.start({
            image: baseImage,
            env: envToInject,
            enableInternet: false,
            instance: 'standard-1',
          });
        }

        const port = container.getTcpPort(CONTAINER_PORT);
        let ready = false;

        for (let attempt = attemptsUsed + 1; attempt <= maxAttempts; attempt++) {
          const timeLeft = deadline - Date.now();
          if (timeLeft <= 0) break;
          const probeBudget = Math.min(healthTimeout, timeLeft);
          const inspectInfo = await this.boundedInspect(container, probeBudget);
          if (inspectInfo.image !== baseImage) throw new Error('CONTAINER_IMAGE_MISMATCH');
          const readinessBudget = Math.min(healthTimeout, deadline - Date.now());
          if (readinessBudget <= 0) throw new Error('CONTAINER_START_TIMEOUT');
          ready = await checkManagedReady(port, env.MANAGEMENT_KEY, readinessBudget);
          if (Date.now() >= deadline) throw new Error('CONTAINER_START_TIMEOUT');
          if (ready) break;
          const remainingAfterProbe = deadline - Date.now();
          if (remainingAfterProbe <= 0 || attempt === maxAttempts) break;
          const sleepMs = Math.min(50, remainingAfterProbe);
          await new Promise((resolve) => setTimeout(resolve, sleepMs));
        }

        if (!ready) throw new Error('CONTAINER_START_TIMEOUT');
        this.activeInstanceConfigHash = configFingerprint;
        return port;
      })().finally(() => {
        this.startPromise = null;
        this.pendingConfigHash = null;
      });
    }

    const startTask = this.startPromise;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let onAbort: (() => void) | undefined;

    const waiterPromise = new Promise<never>((_, reject) => {
      const waitRemaining = deadline - Date.now();
      if (waitRemaining <= 0) {
        reject(new Error('CONTAINER_START_TIMEOUT'));
        return;
      }
      timer = setTimeout(() => reject(new Error('CONTAINER_START_TIMEOUT')), waitRemaining);
      if (signal) {
        onAbort = () => reject(new Error('ABORTED'));
        signal.addEventListener('abort', onAbort, { once: true });
      }
    });

    try {
      return await Promise.race([startTask, waiterPromise]);
    } finally {
      if (timer) clearTimeout(timer);
      if (signal && onAbort) signal.removeEventListener('abort', onAbort);
    }
  }
}
