import type { RemoteReceipt } from './remote-checkpoint.ts';
import { verifyRemoteReceipt } from './verify-remote-receipt.ts';

export interface RemoteCipherExport {
  schema: 'sg.remote-cipher-export.v1';
  receipt: RemoteReceipt;
  body: ReadableStream<Uint8Array>;
}

const HEX32_RE = /^[0-9a-f]{32}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[a-z0-9-]{1,64}$/;
const MAX_BYTES = 64 * 1024 * 1024 + 4136;
const MAX_CHUNK_VIEW = 65536;
const TOTAL_BUDGET_MS = 30000;

function fail(): never {
  throw new Error('Remote cipher export held');
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

function validateRecord(record: unknown): {
  schema: string;
  job_id: string;
  request_digest: string;
  state: string;
  artifact: { leaf: string; bytes: number; sha256: string };
} {
  if (!isPlainObject(record) || !hasExactKeys(record, ['schema', 'job_id', 'request_digest', 'state', 'artifact'])) fail();
  const { schema, job_id, request_digest, state, artifact } = record;
  if (typeof schema !== 'string' || schema !== 'sg.local-job.v1') fail();
  if (typeof job_id !== 'string' || !HEX32_RE.test(job_id)) fail();
  if (typeof request_digest !== 'string' || !HEX64_RE.test(request_digest)) fail();
  if (typeof state !== 'string' || state !== 'artifact-verified') fail();
  if (!isPlainObject(artifact) || !hasExactKeys(artifact, ['leaf', 'bytes', 'sha256'])) fail();
  const { leaf, bytes, sha256 } = artifact;
  if (typeof leaf !== 'string' || !leaf.startsWith('sg-encrypted-') || !leaf.endsWith('.bin')) fail();
  const leafHex = leaf.slice(13, -4);
  if (!HEX32_RE.test(leafHex) || leafHex !== job_id) fail();
  if (typeof bytes !== 'number' || !Number.isInteger(bytes) || bytes < 1 || bytes > MAX_BYTES) fail();
  if (typeof sha256 !== 'string' || !HEX64_RE.test(sha256)) fail();
  return {
    schema,
    job_id,
    request_digest,
    state,
    artifact: { leaf, bytes, sha256 },
  };
}

function validateExpectedReceipt(receipt: unknown): RemoteReceipt {
  if (!isPlainObject(receipt)) fail();
  const exactTopKeys = [
    'schema',
    'state',
    'context',
    'job_id',
    'request_digest',
    'artifact',
    'object_key',
    'object_version',
    'commit_key',
    'commit_version',
  ];
  if (!hasExactKeys(receipt, exactTopKeys)) fail();

  if (receipt.schema !== 'sg.remote-checkpoint.v1') fail();
  if (receipt.state !== 'remote-committed') fail();

  const ctx = receipt.context;
  if (!isPlainObject(ctx) || !hasExactKeys(ctx, ['instanceId', 'runtimeVersion', 'imageDigest', 'keyId'])) fail();
  if (typeof ctx.instanceId !== 'string' || !ID_RE.test(ctx.instanceId)) fail();
  if (typeof ctx.runtimeVersion !== 'string' || ctx.runtimeVersion !== '3.8.50') fail();
  if (typeof ctx.imageDigest !== 'string' || !HEX64_RE.test(ctx.imageDigest)) fail();
  if (typeof ctx.keyId !== 'string' || !ID_RE.test(ctx.keyId)) fail();

  if (typeof receipt.job_id !== 'string' || !HEX32_RE.test(receipt.job_id)) fail();
  if (typeof receipt.request_digest !== 'string' || !HEX64_RE.test(receipt.request_digest)) fail();

  const art = receipt.artifact;
  if (!isPlainObject(art) || !hasExactKeys(art, ['leaf', 'bytes', 'sha256'])) fail();
  if (typeof art.leaf !== 'string' || !art.leaf.startsWith('sg-encrypted-') || !art.leaf.endsWith('.bin')) fail();
  const leafHex = art.leaf.slice(13, -4);
  if (!HEX32_RE.test(leafHex) || leafHex !== receipt.job_id) fail();
  if (typeof art.bytes !== 'number' || !Number.isInteger(art.bytes) || art.bytes < 1 || art.bytes > MAX_BYTES) fail();
  if (typeof art.sha256 !== 'string' || !HEX64_RE.test(art.sha256)) fail();

  if (typeof receipt.object_key !== 'string') fail();
  if (typeof receipt.object_version !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(receipt.object_version)) fail();
  if (typeof receipt.commit_key !== 'string') fail();
  if (typeof receipt.commit_version !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(receipt.commit_version)) fail();

  return {
    schema: 'sg.remote-checkpoint.v1',
    state: 'remote-committed',
    context: {
      instanceId: ctx.instanceId,
      runtimeVersion: ctx.runtimeVersion,
      imageDigest: ctx.imageDigest,
      keyId: ctx.keyId,
    },
    job_id: receipt.job_id,
    request_digest: receipt.request_digest,
    artifact: {
      leaf: art.leaf,
      bytes: art.bytes,
      sha256: art.sha256,
    },
    object_key: receipt.object_key,
    object_version: receipt.object_version,
    commit_key: receipt.commit_key,
    commit_version: receipt.commit_version,
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

function validateObjectMeta(
  obj: R2Object | null,
  expectedKey: string,
  expectedBytes: number,
  expectedSha256: string,
  expectedMetadata: Record<string, string>
): string {
  if (!obj) fail();
  if (typeof obj.key !== 'string' || obj.key !== expectedKey) fail();
  if (typeof obj.version !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(obj.version)) fail();
  if (typeof obj.size !== 'number' || obj.size !== expectedBytes) fail();
  if (!obj.checksums || !(obj.checksums.sha256 instanceof ArrayBuffer)) fail();
  const sha = bufToHex(obj.checksums.sha256);
  if (sha.toLowerCase() !== expectedSha256.toLowerCase()) fail();
  if (!obj.customMetadata || !hasExactKeys(obj.customMetadata, Object.keys(expectedMetadata))) fail();
  for (const [k, v] of Object.entries(expectedMetadata)) {
    if (obj.customMetadata[k] !== v) fail();
  }
  return obj.version;
}

function fireForgetCancel(target: { cancel: (reason?: unknown) => Promise<unknown> } | null | undefined): void {
  if (!target) return;
  try {
    target.cancel().catch(() => {});
  } catch {}
}

function extractBodySafely(target: unknown): { cancel: (reason?: unknown) => Promise<unknown> } | null {
  if (!target || typeof target !== 'object') return null;
  try {
    const b = (target as any).body;
    if (b && typeof b.cancel === 'function') {
      return b;
    }
  } catch {}
  return null;
}

export async function openRemoteCipherExport(
  bucket: Pick<R2Bucket, 'head' | 'get'>,
  context: object,
  localRecord: object,
  expectedReceipt: object,
  signal: AbortSignal
): Promise<RemoteCipherExport> {
  const startEpoch = performance.now();
  const deadline = startEpoch + TOTAL_BUDGET_MS;
  let guardOpen = true;
  const internalController = new AbortController();
  let timerId: any = null;

  const onParentAbort = () => {
    guardOpen = false;
    internalController.abort();
  };

  const cleanup = () => {
    guardOpen = false;
    if (timerId !== null) {
      clearTimeout(timerId);
      timerId = null;
    }
    try {
      signal.removeEventListener('abort', onParentAbort);
    } catch {}
  };

  const checkGuard = () => {
    if (!guardOpen || signal.aborted || internalController.signal.aborted || performance.now() >= deadline) {
      fail();
    }
  };

  const checkFinalGuard = () => {
    if (signal.aborted || internalController.signal.aborted || performance.now() >= deadline) {
      fail();
    }
  };

  const raceDeadline = <T>(promise: Promise<T>): Promise<T> => {
    return new Promise<T>((resolve, reject) => {
      const onAbort = () => {
        internalController.signal.removeEventListener('abort', onAbort);
        reject(new Error('Remote cipher export held'));
      };
      if (!guardOpen || signal.aborted || internalController.signal.aborted || performance.now() >= deadline) {
        promise.then(
          (val) => {
            const b = extractBodySafely(val);
            if (b) fireForgetCancel(b);
          },
          () => {}
        );
        reject(new Error('Remote cipher export held'));
        return;
      }
      internalController.signal.addEventListener('abort', onAbort, {
        once: true,
      });
      promise.then(
        (value) => {
          internalController.signal.removeEventListener('abort', onAbort);
          if (!guardOpen || signal.aborted || internalController.signal.aborted || performance.now() >= deadline) {
            const b = extractBodySafely(value);
            if (b) fireForgetCancel(b);
            reject(new Error('Remote cipher export held'));
          } else {
            resolve(value);
          }
        },
        () => {
          internalController.signal.removeEventListener('abort', onAbort);
          reject(new Error('Remote cipher export held'));
        }
      );
    });
  };

  let cipherReader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  let rawCipherBody: ReadableStream<Uint8Array> | null = null;

  try {
    if (signal.aborted) {
      fail();
    }
    signal.addEventListener('abort', onParentAbort, {
      once: true,
    });

    timerId = setTimeout(() => {
      guardOpen = false;
      internalController.abort();
    }, TOTAL_BUDGET_MS);

    checkGuard();
    const validatedCtx = validateContext(context);
    const validatedRecord = validateRecord(localRecord);
    const validatedExpReceipt = validateExpectedReceipt(expectedReceipt);

    checkGuard();
    let verifiedReceipt: RemoteReceipt;
    try {
      verifiedReceipt = await raceDeadline(
        verifyRemoteReceipt(
          bucket,
          validatedCtx,
          validatedRecord,
          internalController.signal,
          validatedExpReceipt
        )
      );
    } catch {
      fail();
    }

    checkGuard();
    const expectedObjectKey = `cp/v1/${validatedCtx.instanceId}/${validatedCtx.imageDigest}/${validatedRecord.job_id}/${validatedRecord.request_digest}/${validatedRecord.artifact.sha256}.bin`;
    const expectedCommitKey = `cp/v1/${validatedCtx.instanceId}/${validatedCtx.imageDigest}/${validatedRecord.job_id}/${validatedRecord.request_digest}/${validatedRecord.artifact.sha256}.commit.json`;

    if (verifiedReceipt.object_key !== expectedObjectKey || verifiedReceipt.commit_key !== expectedCommitKey) {
      fail();
    }
    if (
      verifiedReceipt.object_version !== validatedExpReceipt.object_version ||
      verifiedReceipt.commit_version !== validatedExpReceipt.commit_version
    ) {
      fail();
    }

    const cipherCustomMetadata: Record<string, string> = {
      instanceId: validatedCtx.instanceId,
      runtimeVersion: validatedCtx.runtimeVersion,
      imageDigest: validatedCtx.imageDigest,
      keyId: validatedCtx.keyId,
      job_id: validatedRecord.job_id,
      request_digest: validatedRecord.request_digest,
      bytes: String(validatedRecord.artifact.bytes),
      sha256: validatedRecord.artifact.sha256,
    };

    checkGuard();
    let cipherGetRes: R2ObjectBody | null = null;
    try {
      cipherGetRes = await raceDeadline(bucket.get(expectedObjectKey).catch(fail));
    } catch {
      fail();
    }
    if (!cipherGetRes) fail();
    try {
      rawCipherBody = cipherGetRes.body as ReadableStream<Uint8Array>;
    } catch {
      fail();
    }
    if (!rawCipherBody) fail();

    const cipherGetVersion = validateObjectMeta(
      cipherGetRes,
      expectedObjectKey,
      validatedRecord.artifact.bytes,
      validatedRecord.artifact.sha256,
      cipherCustomMetadata
    );

    if (cipherGetVersion !== verifiedReceipt.object_version) {
      fail();
    }

    cipherReader = rawCipherBody.getReader();

    const trustedInternalReceipt: RemoteReceipt = {
      schema: 'sg.remote-checkpoint.v1',
      state: 'remote-committed',
      context: {
        instanceId: validatedCtx.instanceId,
        runtimeVersion: validatedCtx.runtimeVersion,
        imageDigest: validatedCtx.imageDigest,
        keyId: validatedCtx.keyId,
      },
      job_id: validatedRecord.job_id,
      request_digest: validatedRecord.request_digest,
      artifact: {
        leaf: validatedRecord.artifact.leaf,
        bytes: validatedRecord.artifact.bytes,
        sha256: validatedRecord.artifact.sha256,
      },
      object_key: verifiedReceipt.object_key,
      object_version: verifiedReceipt.object_version,
      commit_key: verifiedReceipt.commit_key,
      commit_version: verifiedReceipt.commit_version,
    };

    const returnedPublicReceipt: RemoteReceipt = {
      schema: 'sg.remote-checkpoint.v1',
      state: 'remote-committed',
      context: {
        instanceId: validatedCtx.instanceId,
        runtimeVersion: validatedCtx.runtimeVersion,
        imageDigest: validatedCtx.imageDigest,
        keyId: validatedCtx.keyId,
      },
      job_id: validatedRecord.job_id,
      request_digest: validatedRecord.request_digest,
      artifact: {
        leaf: validatedRecord.artifact.leaf,
        bytes: validatedRecord.artifact.bytes,
        sha256: validatedRecord.artifact.sha256,
      },
      object_key: verifiedReceipt.object_key,
      object_version: verifiedReceipt.object_version,
      commit_key: verifiedReceipt.commit_key,
      commit_version: verifiedReceipt.commit_version,
    };

    let totalObservedBytes = 0;
    let currentHostChunk: Uint8Array | null = null;
    let currentHostChunkOffset = 0;
    let heldFinalChunk: Uint8Array | null = null;
    let reachedEOF = false;

    const releaseReader = () => {
      if (cipherReader) {
        try {
          cipherReader.releaseLock();
        } catch {}
        cipherReader = null;
      }
    };

    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;

    const closeStreamFail = (controller?: ReadableStreamDefaultController<Uint8Array>) => {
      guardOpen = false;
      internalController.abort();
      cleanup();
      if (cipherReader) {
        fireForgetCancel(cipherReader);
        releaseReader();
      } else if (rawCipherBody) {
        fireForgetCancel(rawCipherBody);
      }
      const targetCtrl = controller || streamController;
      if (targetCtrl) {
        try {
          targetCtrl.error(new Error('Remote cipher export held'));
        } catch {}
      }
    };

    const onStreamAbort = () => {
        if (cipherReader) {
          fireForgetCancel(cipherReader);
          releaseReader();
        } else if (rawCipherBody) {
          fireForgetCancel(rawCipherBody);
        }
        if (streamController) {
          try {
            streamController.error(new Error('Remote cipher export held'));
          } catch {}
        }
        cleanup();
        internalController.signal.removeEventListener('abort',onStreamAbort);
      };
    internalController.signal.addEventListener('abort',onStreamAbort,{once:true});

    const exportStream = new ReadableStream<Uint8Array>(
      {
        start(controller) {
          streamController = controller;
        },
        async pull(controller) {
          try {
            checkGuard();
            while (true) {
              checkGuard();

              if (currentHostChunk !== null) {
                const remainingInChunk = currentHostChunk.byteLength - currentHostChunkOffset;
                if (remainingInChunk > 0) {
                  const emitSize = Math.min(remainingInChunk, MAX_CHUNK_VIEW);
                  const sliceToEmit = currentHostChunk.subarray(
                    currentHostChunkOffset,
                    currentHostChunkOffset + emitSize
                  );
                  currentHostChunkOffset += emitSize;
                  if (currentHostChunkOffset >= currentHostChunk.byteLength) {
                    currentHostChunk = null;
                    currentHostChunkOffset = 0;
                  }
                  controller.enqueue(sliceToEmit);
                  return;
                } else {
                  currentHostChunk = null;
                  currentHostChunkOffset = 0;
                }
              }

              if (reachedEOF) {
                return;
              }

              if (!cipherReader) {
                closeStreamFail(controller);
                return;
              }

              const readResult = await raceDeadline(cipherReader.read());
              if (readResult.done) {
                reachedEOF = true;
                releaseReader();

                if (totalObservedBytes !== trustedInternalReceipt.artifact.bytes) {
                  closeStreamFail(controller);
                  return;
                }
                if (!heldFinalChunk) {
                  closeStreamFail(controller);
                  return;
                }

                checkGuard();
                let finalVerifiedReceipt: RemoteReceipt;
                try {
                  finalVerifiedReceipt = await raceDeadline(
                    verifyRemoteReceipt(
                      bucket,
                      validatedCtx,
                      validatedRecord,
                      internalController.signal,
                      trustedInternalReceipt
                    )
                  );
                } catch {
                  closeStreamFail(controller);
                  return;
                }

                if (
                  finalVerifiedReceipt.object_version !== trustedInternalReceipt.object_version ||
                  finalVerifiedReceipt.commit_version !== trustedInternalReceipt.commit_version ||
                  finalVerifiedReceipt.object_key !== trustedInternalReceipt.object_key ||
                  finalVerifiedReceipt.commit_key !== trustedInternalReceipt.commit_key
                ) {
                  closeStreamFail(controller);
                  return;
                }

                internalController.signal.removeEventListener('abort',onStreamAbort);
                cleanup();
                checkFinalGuard();

                const chunkToDeliver = heldFinalChunk;
                heldFinalChunk = null;
                controller.enqueue(chunkToDeliver);
                checkFinalGuard();
                controller.close();
                return;
              }

              const chunk = readResult.value;
              if (!chunk || chunk.byteLength === 0) {
                continue;
              }

              totalObservedBytes += chunk.byteLength;
              if (totalObservedBytes > trustedInternalReceipt.artifact.bytes) {
                closeStreamFail(controller);
                return;
              }

              const chunkToProcess = chunk;
              const previousHeld = heldFinalChunk;
              heldFinalChunk = null;

              if (chunkToProcess.byteLength <= MAX_CHUNK_VIEW) {
                heldFinalChunk = chunkToProcess.slice();
                if(previousHeld){controller.enqueue(previousHeld);return;}
              } else {
                const headLength = chunkToProcess.byteLength - MAX_CHUNK_VIEW;
                currentHostChunk = chunkToProcess.subarray(0, headLength);
                currentHostChunkOffset = 0;
                heldFinalChunk = chunkToProcess.slice(headLength);
                if(previousHeld){controller.enqueue(previousHeld);return;}
                const emitSize = Math.min(currentHostChunk.byteLength, MAX_CHUNK_VIEW);
                const sliceToEmit = currentHostChunk.subarray(0, emitSize);
                currentHostChunkOffset = emitSize;
                if (currentHostChunkOffset >= currentHostChunk.byteLength) {
                  currentHostChunk = null;
                  currentHostChunkOffset = 0;
                }
                controller.enqueue(sliceToEmit);
                return;
              }
            }
          } catch {
            closeStreamFail(controller);
          }
        },
        cancel() {
          guardOpen = false;
          internalController.abort();
          cleanup();
          if (cipherReader) {
            fireForgetCancel(cipherReader);
            releaseReader();
          } else if (rawCipherBody) {
            fireForgetCancel(rawCipherBody);
          }
        },
      },
      { highWaterMark: 0 }
    );

    return {
      schema: 'sg.remote-cipher-export.v1',
      receipt: returnedPublicReceipt,
      body: exportStream,
    };
  } catch (err) {
    guardOpen = false;
    internalController.abort();
    cleanup();
    if (cipherReader) {
      fireForgetCancel(cipherReader);
      try {
        cipherReader.releaseLock();
      } catch {}
      cipherReader = null;
    } else if (rawCipherBody) {
      fireForgetCancel(rawCipherBody);
    }
    fail();
  }
}
