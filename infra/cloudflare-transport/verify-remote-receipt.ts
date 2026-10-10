import type { RemoteReceipt } from './remote-checkpoint.ts';

export type { RemoteReceipt };

const HEX32_RE = /^[0-9a-f]{32}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[a-z0-9-]{1,64}$/;
const MAX_BYTES = 64 * 1024 * 1024 + 4136;
const MAX_COMMIT_READ = 2049;

function fail(): never {
  throw new Error('Remote receipt held');
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

export async function verifyRemoteReceipt(
  bucket: Pick<R2Bucket, 'head' | 'get'>,
  context: object,
  record: object,
  signal: AbortSignal,
  expectedReceipt?: object
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
      const onAbort = () => {
        abortController.signal.removeEventListener('abort', onAbort);
        reject(new Error('Remote receipt held'));
      };
      if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
        promise.catch(() => {});
        reject(new Error('Remote receipt held'));
        return;
      }
      abortController.signal.addEventListener('abort', onAbort, { once: true });
      promise.then(
        (value) => {
          abortController.signal.removeEventListener('abort', onAbort);
          if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
            try {
              const body = value && (value as any).body;
              if (body && typeof body.cancel === 'function') fireForgetCancel(body);
            } catch {}
            reject(new Error('Remote receipt held'));
          } else {
            resolve(value);
          }
        },
        () => {
          abortController.signal.removeEventListener('abort', onAbort);
          reject(new Error('Remote receipt held'));
        }
      );
    });
  };

  let receivedBody: ReadableStream<Uint8Array> | null = null;
  try {
    checkGuard();
    const ctx = validateContext(context);
    const rec = validateRecord(record);
    const exp = expectedReceipt !== undefined ? validateExpectedReceipt(expectedReceipt) : null;

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

    if (exp !== null) {
      if (exp.schema !== 'sg.remote-checkpoint.v1') fail();
      if (exp.state !== 'remote-committed') fail();
      if (exp.context.instanceId !== ctx.instanceId) fail();
      if (exp.context.runtimeVersion !== ctx.runtimeVersion) fail();
      if (exp.context.imageDigest !== ctx.imageDigest) fail();
      if (exp.context.keyId !== ctx.keyId) fail();
      if (exp.job_id !== rec.job_id) fail();
      if (exp.request_digest !== rec.request_digest) fail();
      if (exp.artifact.leaf !== rec.artifact.leaf) fail();
      if (exp.artifact.bytes !== rec.artifact.bytes) fail();
      if (exp.artifact.sha256 !== rec.artifact.sha256) fail();
      if (exp.object_key !== objectKey) fail();
      if (exp.commit_key !== commitKey) fail();
    }

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
    const initialCipherHead = await raceDeadline(bucket.head(objectKey).catch(fail));
    const initialCipherVersion = validateObjectMeta(
      initialCipherHead,
      objectKey,
      rec.artifact.bytes,
      rec.artifact.sha256,
      cipherCustomMetadata
    );

    if (exp !== null && exp.object_version !== initialCipherVersion) fail();

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
      object_version: initialCipherVersion,
      request_digest: rec.request_digest,
      schema: 'sg.commit-record.v1',
    };
    const canonicalCommitStr = canonicalJson(commitPayload);
    const commitBytes = new TextEncoder().encode(canonicalCommitStr);
    if (commitBytes.byteLength > 2048) fail();
    const commitSha = await raceDeadline(sha256Hex(commitBytes));

    const commitCustomMetadata: Record<string, string> = {
      kind: 'commit',
      runtimeVersion: ctx.runtimeVersion,
      imageDigest: ctx.imageDigest,
      keyId: ctx.keyId,
      instanceId: ctx.instanceId,
      job_id: rec.job_id,
      request_digest: rec.request_digest,
      object_version: initialCipherVersion,
    };

    checkGuard();
    const commitGetRes = await raceDeadline(bucket.get(commitKey).catch(fail));
    if (!commitGetRes) fail();
    receivedBody = commitGetRes.body;

    const initialCommitVersion = validateObjectMeta(
      commitGetRes,
      commitKey,
      commitBytes.byteLength,
      commitSha,
      commitCustomMetadata
    );

    if (initialCommitVersion === initialCipherVersion) fail();
    if (exp !== null && exp.commit_version !== initialCommitVersion) fail();

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
        try {
          bodyReader.releaseLock();
        } catch {}
      }
      if (readBuf.byteLength !== commitBytes.byteLength) fail();
      for (let i = 0; i < commitBytes.byteLength; i++) {
        if (readBuf[i] !== commitBytes[i]) fail();
      }
    };

    await readExactCommitBody(commitGetRes.body as ReadableStream<Uint8Array>);
    receivedBody = null;

    checkGuard();
    const finalCipherHead = await raceDeadline(bucket.head(objectKey).catch(fail));
    const finalCipherVersion = validateObjectMeta(
      finalCipherHead,
      objectKey,
      rec.artifact.bytes,
      rec.artifact.sha256,
      cipherCustomMetadata
    );
    if (finalCipherVersion !== initialCipherVersion) fail();

    checkGuard();
    const finalCommitHead = await raceDeadline(bucket.head(commitKey).catch(fail));
    const finalCommitVersion = validateObjectMeta(
      finalCommitHead,
      commitKey,
      commitBytes.byteLength,
      commitSha,
      commitCustomMetadata
    );
    if (finalCommitVersion !== initialCommitVersion) fail();

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
      object_version: initialCipherVersion,
      commit_key: commitKey,
      commit_version: initialCommitVersion,
    };

    return receipt;
  } catch {
    guardOpen = false;
    abortController.abort();
    fireForgetCancel(receivedBody);
    fail();
  } finally {
    cleanup();
    if (signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
      fail();
    }
  }
  throw new Error('Remote receipt held');
}
