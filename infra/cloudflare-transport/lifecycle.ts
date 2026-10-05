export interface LifecycleEnv {
  STORAGE_ENCRYPTION_KEY: string;
  GATEWAY_START_ALLOWED: string;
}

export const LIFECYCLE_OVERALL_TIMEOUT_MS = 5000;
export const LIFECYCLE_HEALTH_TIMEOUT_MS = 1000;
export const LIFECYCLE_MAX_ATTEMPTS = 5;
export const CONTAINER_PORT = 8081;
export const MAX_ADMIN_HEALTH_BYTES = 16;

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

export class ContainerLifecycleManager {
  private startPromise: Promise<Fetcher> | null = null;

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
    if (signal?.aborted) {
      throw new Error('ABORTED');
    }

    if (env.GATEWAY_START_ALLOWED !== 'true') {
      throw new Error('GATEWAY_START_HOLD');
    }

    if (!container) {
      throw new Error('CONTAINER_UNAVAILABLE');
    }

    if (
      !env.STORAGE_ENCRYPTION_KEY ||
      typeof env.STORAGE_ENCRYPTION_KEY !== 'string' ||
      env.STORAGE_ENCRYPTION_KEY.length < 24 ||
      env.STORAGE_ENCRYPTION_KEY.length > 4096
    ) {
      throw new Error('INVALID_STORAGE_ENCRYPTION_KEY');
    }

    const baseImage = container.images?.base;
    if (!baseImage) {
      throw new Error('CONTAINER_IMAGE_NOT_FOUND');
    }

    const overallTimeout = validatePositiveFiniteBound(overrides?.overallTimeoutMs, LIFECYCLE_OVERALL_TIMEOUT_MS, LIFECYCLE_OVERALL_TIMEOUT_MS);
    const healthTimeout = validatePositiveFiniteBound(overrides?.healthTimeoutMs, LIFECYCLE_HEALTH_TIMEOUT_MS, LIFECYCLE_HEALTH_TIMEOUT_MS);
    const maxAttempts = validatePositiveFiniteBound(overrides?.maxAttempts, LIFECYCLE_MAX_ATTEMPTS, LIFECYCLE_MAX_ATTEMPTS);

    const deadline = Date.now() + overallTimeout;

    let attemptsUsed = 0;
    if (container.running && !this.startPromise) {
      const port = container.getTcpPort(CONTAINER_PORT);
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new Error('CONTAINER_START_TIMEOUT');
      const singleHealthBudget = Math.min(healthTimeout, remaining);
      attemptsUsed++;
      const isHealthy = await checkPortHealth(port, singleHealthBudget, signal);
      if (signal?.aborted) throw new Error('ABORTED');
      if (isHealthy) {
        return port;
      }
    }

    if (!this.startPromise) {
      this.startPromise = (async () => {
        if (!container.running) {
          container.start({
            image: baseImage,
            env: { STORAGE_ENCRYPTION_KEY: env.STORAGE_ENCRYPTION_KEY },
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
          ready = await checkPortHealth(port, probeBudget);
          if (ready) break;
          const remainingAfterProbe = deadline - Date.now();
          if (remainingAfterProbe <= 0 || attempt === maxAttempts) break;
          const sleepMs = Math.min(50, remainingAfterProbe);
          await new Promise((resolve) => setTimeout(resolve, sleepMs));
        }

        if (!ready) {
          throw new Error('CONTAINER_START_TIMEOUT');
        }

        return port;
      })().finally(() => {
        this.startPromise = null;
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
