export interface RemoteReceipt {
  schema: 'sg.remote-checkpoint.v1';
  state: 'remote-committed';
  context: {
    instanceId: string;
    runtimeVersion: string;
    imageDigest: string;
    keyId: string;
  };
  job_id: string;
  request_digest: string;
  artifact: {
    leaf: string;
    bytes: number;
    sha256: string;
  };
  object_key: string;
  object_version: string;
  commit_key: string;
  commit_version: string;
}

const HEX32_RE = /^[0-9a-f]{32}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[a-z0-9-]{1,64}$/;
const MAX_BYTES = 64 * 1024 * 1024 + 4136;
const MAX_CHUNK_SIZE = 65536;
const MAX_COMMIT_READ = 2049;

function fail(): never {
  throw new Error('Remote checkpoint held');
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
    job_id,
    request_digest,
    state,
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

function hexToBuf(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
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

function fireForgetCancel(target: { cancel: () => Promise<unknown> } | null | undefined): void {
  if (!target) return;
  try {
    target.cancel().catch(() => {});
  } catch {}
}

export async function commitRemoteCheckpoint(
  bucket: Pick<R2Bucket, 'put' | 'head' | 'get'>,
  context: object,
  record: object,
  source: ReadableStream<Uint8Array>,
  signal: AbortSignal
): Promise<RemoteReceipt> {
  const deadline = performance.now() + 30000;
  let guardOpen = true;
  const abortController = new AbortController();
  let timeoutId: any = null;

  const cleanup = () => {
    guardOpen = false;
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    try {
      signal.removeEventListener('abort', onSignalAbort);
    } catch {}
  };

  const onSignalAbort = () => {
    guardOpen = false;
    abortController.abort();
  };

  if (signal.aborted) {
    guardOpen = false;
    fail();
  }
  signal.addEventListener('abort', onSignalAbort, { once: true });
  timeoutId = setTimeout(() => {
    guardOpen = false;
    abortController.abort();
  }, 30000);

  const checkGuard = () => {
    if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) fail();
  };

  const raceDeadline = <T>(promise: Promise<T>): Promise<T> => {
    return new Promise<T>((resolve, reject) => {
      const cleanup = () => abortController.signal.removeEventListener('abort', onAbort);
      const onAbort = () => {
        cleanup();
        reject(new Error('Remote checkpoint held'));
      };
      if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
        promise.catch(() => {});
        reject(new Error('Remote checkpoint held'));
        return;
      }
      abortController.signal.addEventListener('abort', onAbort, { once: true });
      promise.then(value => {
        cleanup();
        if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
          reject(new Error('Remote checkpoint held'));
        } else resolve(value);
      }, () => {
        cleanup();
        reject(new Error('Remote checkpoint held'));
      });
    });
  };

  let sourceReader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  try {
    checkGuard();
    const ctx = validateContext(context);
    const rec = validateRecord(record);

    const expectedReqObj = {
      context: {
        imageDigest: ctx.imageDigest,
        instanceId: ctx.instanceId,
        keyId: ctx.keyId,
        runtimeVersion: ctx.runtimeVersion,
      },
      operation: 'checkpoint',
      request: { job_id: rec.job_id },
      schema: 'sg.operation-request.v1',
    };
    const canonicalReqJson = canonicalJson(expectedReqObj);
    const expectedReqDigest = await raceDeadline(sha256Hex(new TextEncoder().encode(canonicalReqJson)));
    if (expectedReqDigest !== rec.request_digest) fail();

    checkGuard();
    const objectKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${rec.job_id}/${rec.request_digest}/${rec.artifact.sha256}.bin`;
    const commitKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${rec.job_id}/${rec.request_digest}/${rec.artifact.sha256}.commit.json`;

    const cipherCustomMetadata: Record<string, string> = {
      instanceId: ctx.instanceId,
      runtimeVersion: ctx.runtimeVersion,
      imageDigest: ctx.imageDigest,
      keyId: ctx.keyId,
      job_id: rec.job_id,
      request_digest: rec.request_digest,
      bytes: String(rec.artifact.bytes),
      sha256: rec.artifact.sha256,
    };

    checkGuard();
    const headPromise = bucket.head(objectKey).catch(fail);
    const existingHead = await raceDeadline(headPromise);
    let objectVersion: string | null = null;

    if (existingHead !== null) {
      objectVersion = validateObjectMeta(existingHead, objectKey, rec.artifact.bytes, rec.artifact.sha256, cipherCustomMetadata);
      try {
        sourceReader = source.getReader();
        fireForgetCancel(sourceReader);
      } catch {}
    } else {
      checkGuard();
      const fls = new FixedLengthStream(rec.artifact.bytes);
      const writer = fls.writable.getWriter();
      sourceReader = source.getReader();

      let totalPumped = 0;
      let pumpFailed = false;
      let pumpFinished = false;

      const pumpPromise = (async () => {
        try {
          while (true) {
            if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) throw new Error('held');
            const { done, value } = await sourceReader!.read();
            if (done) {
              if (totalPumped !== rec.artifact.bytes) throw new Error('held');
              pumpFinished = true;
              await writer.close();
              break;
            }
            if (!value || value.byteLength === 0) continue;
            if (value.byteLength > MAX_CHUNK_SIZE) throw new Error('held');
            totalPumped += value.byteLength;
            if (totalPumped > rec.artifact.bytes) throw new Error('held');
            if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) throw new Error('held');
            await writer.write(value);
          }
        } catch (err) {
          pumpFailed = true;
          try { writer.abort(err).catch(() => {}); } catch {}
          throw err;
        }
      })();

      const putHeaders = new Headers();
      putHeaders.set('If-None-Match', '*');

      const rawShaBuf = hexToBuf(rec.artifact.sha256);

      let putResultPromise: Promise<R2Object | null>;
      try {
        putResultPromise = bucket.put(objectKey, fls.readable, {
          onlyIf: putHeaders,
          sha256: rawShaBuf,
          customMetadata: cipherCustomMetadata,
        });
      } catch {
        guardOpen = false;
        fail();
      }

      putResultPromise.catch(() => {});
      pumpPromise.catch(() => {});

      let putRes: R2Object | null = null;
      try {
        putRes = await raceDeadline(putResultPromise);
      } catch {
        guardOpen = false;
        fail();
      }

      if (putRes === null) {
        fireForgetCancel(sourceReader);
        checkGuard();
        const collidedHead = await raceDeadline(bucket.head(objectKey).catch(fail));
        objectVersion = validateObjectMeta(collidedHead, objectKey, rec.artifact.bytes, rec.artifact.sha256, cipherCustomMetadata);
      } else {
        await raceDeadline(pumpPromise.catch(fail));
        if (pumpFailed || !pumpFinished || totalPumped !== rec.artifact.bytes) fail();
        validateObjectMeta(putRes, objectKey, rec.artifact.bytes, rec.artifact.sha256, cipherCustomMetadata);
        checkGuard();
        const headAfterPut = await raceDeadline(bucket.head(objectKey).catch(fail));
        objectVersion = validateObjectMeta(headAfterPut, objectKey, rec.artifact.bytes, rec.artifact.sha256, cipherCustomMetadata);
        if (objectVersion !== putRes.version) fail();
      }
    }

    if (!objectVersion) fail();

    checkGuard();
    const commitPayload = {
      artifact: {
        bytes: rec.artifact.bytes,
        leaf: rec.artifact.leaf,
        sha256: rec.artifact.sha256,
      },
      context: {
        imageDigest: ctx.imageDigest,
        instanceId: ctx.instanceId,
        keyId: ctx.keyId,
        runtimeVersion: ctx.runtimeVersion,
      },
      job_id: rec.job_id,
      object_key: objectKey,
      object_version: objectVersion,
      request_digest: rec.request_digest,
      schema: 'sg.commit-record.v1',
    };
    const canonicalCommitStr = canonicalJson(commitPayload);
    const commitBytes = new TextEncoder().encode(canonicalCommitStr);
    if (commitBytes.byteLength > 2048) fail();
    const commitSha = await raceDeadline(sha256Hex(commitBytes));
    const rawCommitShaBuf = hexToBuf(commitSha);

    const commitCustomMetadata: Record<string, string> = {
      kind: 'commit',
      runtimeVersion: ctx.runtimeVersion,
      imageDigest: ctx.imageDigest,
      keyId: ctx.keyId,
      instanceId: ctx.instanceId,
      job_id: rec.job_id,
      request_digest: rec.request_digest,
      object_version: objectVersion,
    };

    const readExactCommitBody = async (bodyStream: ReadableStream<Uint8Array>): Promise<void> => {
      const bodyReader = bodyStream.getReader();
      let readBuf = new Uint8Array(0);
      try {
        while (true) {
          checkGuard();
          const { done, value } = await raceDeadline(bodyReader.read());
          if (done) break;
          if (value) {
            if (readBuf.byteLength + value.byteLength > MAX_COMMIT_READ) fail();
            const next = new Uint8Array(readBuf.byteLength + value.byteLength);
            next.set(readBuf);
            next.set(value, readBuf.byteLength);
            readBuf = next;
          }
        }
      } catch (err) {
        fireForgetCancel(bodyReader);
        throw err;
      } finally {
        try { bodyReader.releaseLock(); } catch {}
      }
      if (readBuf.byteLength !== commitBytes.byteLength) fail();
      for (let i = 0; i < commitBytes.byteLength; i++) {
        if (readBuf[i] !== commitBytes[i]) fail();
      }
    };

    checkGuard();
    const existingCommit = await raceDeadline(bucket.get(commitKey).catch(fail));
    let commitVersion: string | null = null;

    if (existingCommit !== null) {
      validateObjectMeta(existingCommit, commitKey, commitBytes.byteLength, commitSha, commitCustomMetadata);
      if (typeof existingCommit.size !== 'number' || existingCommit.size !== commitBytes.byteLength) fail();
      if (typeof existingCommit.version !== 'string' || existingCommit.version.length === 0 || existingCommit.version.length > 256) fail();
      if (existingCommit.version === objectVersion) fail();
      if (!existingCommit.checksums || !(existingCommit.checksums.sha256 instanceof ArrayBuffer)) fail();
      if (bufToHex(existingCommit.checksums.sha256).toLowerCase() !== commitSha.toLowerCase()) fail();
      if (!existingCommit.customMetadata) fail();
      for (const [k, v] of Object.entries(commitCustomMetadata)) {
        if (existingCommit.customMetadata[k] !== v) fail();
      }
      await readExactCommitBody(existingCommit.body as ReadableStream<Uint8Array>);
      commitVersion = existingCommit.version;
    } else {
      checkGuard();
      const commitPutHeaders = new Headers();
      commitPutHeaders.set('If-None-Match', '*');

      let commitPutPromise: Promise<R2Object | null>;
      try {
        commitPutPromise = bucket.put(commitKey, commitBytes, {
          onlyIf: commitPutHeaders,
          sha256: rawCommitShaBuf,
          customMetadata: commitCustomMetadata,
        });
      } catch {
        guardOpen = false;
        fail();
      }
      commitPutPromise.catch(() => {});
      const putCommitRes = await raceDeadline(commitPutPromise);

      checkGuard();
      const verifyCommitGet = await raceDeadline(bucket.get(commitKey).catch(fail));
      if (!verifyCommitGet) fail();
      validateObjectMeta(verifyCommitGet, commitKey, commitBytes.byteLength, commitSha, commitCustomMetadata);
      if (putCommitRes !== null) validateObjectMeta(putCommitRes, commitKey, commitBytes.byteLength, commitSha, commitCustomMetadata);
      if (typeof verifyCommitGet.size !== 'number' || verifyCommitGet.size !== commitBytes.byteLength) fail();
      if (typeof verifyCommitGet.version !== 'string' || verifyCommitGet.version.length === 0 || verifyCommitGet.version.length > 256) fail();
      if (verifyCommitGet.version === objectVersion) fail();
      if (putCommitRes !== null && putCommitRes.version !== verifyCommitGet.version) fail();
      if (!verifyCommitGet.checksums || !(verifyCommitGet.checksums.sha256 instanceof ArrayBuffer)) fail();
      if (bufToHex(verifyCommitGet.checksums.sha256).toLowerCase() !== commitSha.toLowerCase()) fail();
      if (!verifyCommitGet.customMetadata) fail();
      for (const [k, v] of Object.entries(commitCustomMetadata)) {
        if (verifyCommitGet.customMetadata[k] !== v) fail();
      }
      await readExactCommitBody(verifyCommitGet.body as ReadableStream<Uint8Array>);
      commitVersion = verifyCommitGet.version;
    }

    if (!commitVersion) fail();
    checkGuard();

    const receipt: RemoteReceipt = {
      schema: 'sg.remote-checkpoint.v1',
      state: 'remote-committed',
      context: {
        instanceId: ctx.instanceId,
        runtimeVersion: ctx.runtimeVersion,
        imageDigest: ctx.imageDigest,
        keyId: ctx.keyId,
      },
      job_id: rec.job_id,
      request_digest: rec.request_digest,
      artifact: {
        leaf: rec.artifact.leaf,
        bytes: rec.artifact.bytes,
        sha256: rec.artifact.sha256,
      },
      object_key: objectKey,
      object_version: objectVersion,
      commit_key: commitKey,
      commit_version: commitVersion,
    };
    return receipt;
  } catch {
    guardOpen = false;
    fireForgetCancel(sourceReader);
    fail();
  } finally {
    cleanup();
  }
}
