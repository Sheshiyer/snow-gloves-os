import { commitRemoteCheckpoint, type RemoteReceipt } from './remote-checkpoint.ts';

export type { RemoteReceipt };

const HEX32_RE = /^[0-9a-f]{32}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[a-z0-9-]{1,64}$/;
const BEARER_RE = /^[A-Za-z0-9._~-]{32,256}$/;
const CONTENT_LENGTH_RE = /^[1-9][0-9]*$/;
const MAX_BYTES = 64 * 1024 * 1024 + 4136;
const CHUNK_SIZE = 65536;
const EXPORT_TARGET = 'http://runtime.internal:8080/_management/export';

function fail(): never {
  throw new Error('Export checkpoint held');
}

function isPlainObject(val: unknown): val is Record<string, unknown> {
  if (typeof val !== 'object' || val === null || Array.isArray(val)) return false;
  const proto = Object.getPrototypeOf(val);
  return proto === Object.prototype || proto === null;
}

function hasExactKeys(obj: Record<string, unknown>, keys: string[]): boolean {
  const objKeys = Object.keys(obj);
  if (objKeys.length !== keys.length) return false;
  for (const k of keys) {
    if (!Object.prototype.hasOwnProperty.call(obj, k)) return false;
  }
  return true;
}

function validateContext(ctx: unknown): {
  instanceId: string;
  runtimeVersion: string;
  imageDigest: string;
  keyId: string;
} {
  if (!isPlainObject(ctx) || !hasExactKeys(ctx, ['instanceId', 'runtimeVersion', 'imageDigest', 'keyId'])) fail();
  const { instanceId, runtimeVersion, imageDigest, keyId } = ctx;
  if (typeof instanceId !== 'string' || !ID_RE.test(instanceId)) fail();
  if (typeof runtimeVersion !== 'string' || runtimeVersion !== '3.8.50') fail();
  if (typeof imageDigest !== 'string' || !HEX64_RE.test(imageDigest)) fail();
  if (typeof keyId !== 'string' || !ID_RE.test(keyId)) fail();
  return { instanceId, runtimeVersion, imageDigest, keyId };
}

function validatePayload(pld: unknown): {
  job_id: string;
  request_digest: string;
} {
  if (!isPlainObject(pld) || !hasExactKeys(pld, ['job_id', 'request_digest'])) fail();
  const { job_id, request_digest } = pld;
  if (typeof job_id !== 'string' || !HEX32_RE.test(job_id)) fail();
  if (typeof request_digest !== 'string' || !HEX64_RE.test(request_digest)) fail();
  return { job_id, request_digest };
}

function validateHeaderRecord(record: unknown, expectedJobId: string, expectedDigest: string): {
  schema: 'sg.local-job.v1';
  job_id: string;
  request_digest: string;
  state: 'artifact-verified';
  artifact: { leaf: string; bytes: number; sha256: string };
} {
  if (!isPlainObject(record) || !hasExactKeys(record, ['schema', 'job_id', 'request_digest', 'state', 'artifact'])) fail();
  const { schema, job_id, request_digest, state, artifact } = record;
  if (typeof schema !== 'string' || schema !== 'sg.local-job.v1') fail();
  if (typeof job_id !== 'string' || job_id !== expectedJobId) fail();
  if (typeof request_digest !== 'string' || request_digest !== expectedDigest) fail();
  if (typeof state !== 'string' || state !== 'artifact-verified') fail();
  if (!isPlainObject(artifact) || !hasExactKeys(artifact, ['leaf', 'bytes', 'sha256'])) fail();
  const { leaf, bytes, sha256 } = artifact;
  if (typeof leaf !== 'string' || leaf !== `sg-encrypted-${expectedJobId}.bin`) fail();
  if (typeof bytes !== 'number' || !Number.isInteger(bytes) || bytes < 1 || bytes > MAX_BYTES) fail();
  if (typeof sha256 !== 'string' || !HEX64_RE.test(sha256)) fail();
  return {
    schema: 'sg.local-job.v1',
    job_id,
    request_digest,
    state: 'artifact-verified',
    artifact: { leaf, bytes, sha256 },
  };
}

function bufToHex(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0');
  }
  return hex;
}

async function sha256Hex(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data);
  return bufToHex(digest);
}

function canonicalJson(obj: unknown): string {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(canonicalJson).join(',') + ']';
  }
  const keys = Object.keys(obj as Record<string, unknown>).sort();
  const entries = keys.map((k) => JSON.stringify(k) + ':' + canonicalJson((obj as Record<string, unknown>)[k]));
  return '{' + entries.join(',') + '}';
}

function fireForgetCancel(target: { cancel: (reason?: unknown) => Promise<unknown> } | null | undefined, reason?: unknown): void {
  if (!target) return;
  try {
    target.cancel(reason).catch(() => {});
  } catch {}
}

export async function commitExportCipherToRemote(
  bucket: Pick<R2Bucket, 'put' | 'head' | 'get'>,
  fetcher: { fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> },
  context: object,
  payload: object,
  managementBearer: string,
  signal: AbortSignal
): Promise<RemoteReceipt> {
  const deadline = performance.now() + 30000;
  let guardOpen = true;
  const sharedAbortController = new AbortController();
  const fetchAbortController = new AbortController();
  let timeoutId: any = null;

  const onSharedAbort = () => {
    if (!fetchAbortController.signal.aborted) {
      try {
        fetchAbortController.abort();
      } catch {}
    }
  };
  sharedAbortController.signal.addEventListener('abort', onSharedAbort, { once: true });

  const cleanup = () => {
    guardOpen = false;
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    try {
      signal.removeEventListener('abort', onSignalAbort);
    } catch {}
    try {
      sharedAbortController.signal.removeEventListener('abort', onSharedAbort);
    } catch {}
  };

  const onSignalAbort = () => {
    guardOpen = false;
    sharedAbortController.abort();
    if (!fetchAbortController.signal.aborted) {
      try {
        fetchAbortController.abort();
      } catch {}
    }
  };

  if (signal.aborted) {
    guardOpen = false;
    fetchAbortController.abort();
    sharedAbortController.abort();
    fail();
  }
  signal.addEventListener('abort', onSignalAbort, { once: true });
  timeoutId = setTimeout(() => {
    guardOpen = false;
    sharedAbortController.abort();
    if (!fetchAbortController.signal.aborted) {
      try {
        fetchAbortController.abort();
      } catch {}
    }
  }, 30000);

  const checkGuard = () => {
    if (!guardOpen || signal.aborted || sharedAbortController.signal.aborted || performance.now() >= deadline) fail();
  };

  const raceDeadline = <T>(promise: Promise<T>): Promise<T> => {
    return new Promise<T>((resolve, reject) => {
      const cleanupListener = () => sharedAbortController.signal.removeEventListener('abort', onAbort);
      const onAbort = () => {
        cleanupListener();
        reject(new Error('Export checkpoint held'));
      };
      if (!guardOpen || signal.aborted || sharedAbortController.signal.aborted || performance.now() >= deadline) {
        promise.catch(() => {});
        reject(new Error('Export checkpoint held'));
        return;
      }
      sharedAbortController.signal.addEventListener('abort', onAbort, { once: true });
      promise.then(
        (value) => {
          cleanupListener();
          if (!guardOpen || signal.aborted || sharedAbortController.signal.aborted || performance.now() >= deadline) {
            reject(new Error('Export checkpoint held'));
          } else {
            resolve(value);
          }
        },
        (err) => {
          cleanupListener();
          reject(err instanceof Error ? err : new Error('Export checkpoint held'));
        }
      );
    });
  };

  let receivedResponse: Response | null = null;
  let bodyReader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  try {
    checkGuard();
    if (typeof managementBearer !== 'string' || !BEARER_RE.test(managementBearer)) fail();
    const ctx = validateContext(context);
    const pld = validatePayload(payload);

    const canonicalReqObj = {
      context: {
        imageDigest: ctx.imageDigest,
        instanceId: ctx.instanceId,
        keyId: ctx.keyId,
        runtimeVersion: ctx.runtimeVersion,
      },
      operation: 'checkpoint',
      request: { job_id: pld.job_id },
      schema: 'sg.operation-request.v1',
    };
    const canonicalReqJson = canonicalJson(canonicalReqObj);
    const reqDigest = await raceDeadline(sha256Hex(new TextEncoder().encode(canonicalReqJson)));
    if (reqDigest !== pld.request_digest) fail();

    checkGuard();
    const rawPayloadBody = JSON.stringify(pld);
    const fetchInit: RequestInit & { credentials: 'omit' } = {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${managementBearer}`,
        'Content-Type': 'application/json',
      },
      body: rawPayloadBody,
      redirect: 'manual',
      credentials: 'omit',
      signal: fetchAbortController.signal,
    };
    const fetchPromise = fetcher.fetch(EXPORT_TARGET, fetchInit).then((res) => {
      if (!guardOpen || sharedAbortController.signal.aborted || signal.aborted || performance.now() >= deadline) {
        if (res && res.body) {
          fireForgetCancel(res.body);
        }
      }
      return res;
    }).catch((err) => {
      fail();
    });

    const res = await raceDeadline(fetchPromise);
    receivedResponse = res;
    checkGuard();

    if (!res || res.status !== 200 || !res.body) fail();

    const ct = res.headers.get('content-type');
    if (ct !== 'application/vnd.sg.cipher-export+v1') fail();

    if (res.headers.has('transfer-encoding') || res.headers.has('content-encoding')) fail();

    const clHeader = res.headers.get('content-length');
    if (!clHeader || !CONTENT_LENGTH_RE.test(clHeader)) fail();
    const contentLength = parseInt(clHeader, 10);
    if (contentLength < 1 || contentLength > MAX_BYTES) fail();

    const cc = res.headers.get('cache-control');
    if (cc !== 'no-store') fail();

    const conn = res.headers.get('connection');
    if (conn === null || conn.toLowerCase() !== 'close') fail();

    const headerContextRaw = res.headers.get('x-sg-export-context');
    if (!headerContextRaw || headerContextRaw.length > 2048 || !/^[\x20-\x7e]+$/.test(headerContextRaw)) fail();
    let parsedHeaderContext: unknown;
    try {
      parsedHeaderContext = JSON.parse(headerContextRaw);
    } catch {
      fail();
    }
    const headerCtx = validateContext(parsedHeaderContext);
    if (
      headerCtx.instanceId !== ctx.instanceId ||
      headerCtx.runtimeVersion !== ctx.runtimeVersion ||
      headerCtx.imageDigest !== ctx.imageDigest ||
      headerCtx.keyId !== ctx.keyId
    ) {
      fail();
    }

    const headerRecordRaw = res.headers.get('x-sg-export-record');
    if (!headerRecordRaw || headerRecordRaw.length > 2048 || !/^[\x20-\x7e]+$/.test(headerRecordRaw)) fail();
    let parsedHeaderRecord: unknown;
    try {
      parsedHeaderRecord = JSON.parse(headerRecordRaw);
    } catch {
      fail();
    }
    const record = validateHeaderRecord(parsedHeaderRecord, pld.job_id, pld.request_digest);
    if (record.artifact.bytes !== contentLength) fail();

    const digestHeader = res.headers.get('x-sg-export-digest');
    if (!digestHeader || digestHeader !== record.artifact.sha256) fail();

    bodyReader = res.body.getReader();
    let pendingChunk: Uint8Array | null = null;
    let pendingOffset = 0;
    let totalObserved = 0;
    let totalEmitted = 0;
    let streamClosed = false;

    const sourceStream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          checkGuard();
          if (pendingChunk !== null) {
            const remaining = pendingChunk.byteLength - pendingOffset;
            const emitSize = Math.min(remaining, CHUNK_SIZE);
            const chunk = pendingChunk.subarray(pendingOffset, pendingOffset + emitSize);
            pendingOffset += emitSize;
            totalEmitted += emitSize;
            if (pendingOffset >= pendingChunk.byteLength) {
              pendingChunk = null;
              pendingOffset = 0;
            }
            controller.enqueue(chunk);
            return;
          }

          while (true) {
            checkGuard();
            const { done, value } = await raceDeadline(bodyReader!.read());
            if (done) {
              if (totalObserved !== record.artifact.bytes || totalEmitted !== record.artifact.bytes) {
                fail();
              }
              streamClosed = true;
              try {
                bodyReader!.releaseLock();
              } catch {}
              controller.close();
              return;
            }

            if (!value || value.byteLength === 0) {
              continue;
            }

            totalObserved += value.byteLength;
            if (totalObserved > record.artifact.bytes) {
              fail();
            }

            const emitSize = Math.min(value.byteLength, CHUNK_SIZE);
            const chunk = value.subarray(0, emitSize);
            totalEmitted += emitSize;
            if (emitSize < value.byteLength) {
              pendingChunk = value;
              pendingOffset = emitSize;
            } else {
              pendingChunk = null;
              pendingOffset = 0;
            }
            controller.enqueue(chunk);
            return;
          }
        } catch (streamErr) {
          if (bodyReader) {
            fireForgetCancel(bodyReader, streamErr);
            try {
              bodyReader.releaseLock();
            } catch {}
          }
          controller.error(new Error('Export checkpoint held'));
          throw new Error('Export checkpoint held');
        }
      },
      cancel(reason) {
        if (!streamClosed && bodyReader) {
          fireForgetCancel(bodyReader, reason);
          try {
            bodyReader.releaseLock();
          } catch {}
        }
        if (!fetchAbortController.signal.aborted) {
          try {
            fetchAbortController.abort();
          } catch {}
        }
      },
    }, { highWaterMark: 0 });

    checkGuard();
    const receiptPromise = commitRemoteCheckpoint(
      bucket,
      ctx,
      record,
      sourceStream,
      sharedAbortController.signal
    ).catch(() => fail());

    const receipt = await raceDeadline(receiptPromise);
    checkGuard();
    return receipt;
  } catch {
    guardOpen = false;
    sharedAbortController.abort();
    if (!fetchAbortController.signal.aborted) {
      try {
        fetchAbortController.abort();
      } catch {}
    }
    if (bodyReader) {
      fireForgetCancel(bodyReader);
      try {
        bodyReader.releaseLock();
      } catch {}
    } else if (receivedResponse && receivedResponse.body) {
      fireForgetCancel(receivedResponse.body);
    }
    fail();
  } finally {
    cleanup();
    if (signal.aborted || sharedAbortController.signal.aborted || performance.now() >= deadline) {
      sharedAbortController.abort();
      fail();
    }
  }
  throw new Error('Export checkpoint held');
}
