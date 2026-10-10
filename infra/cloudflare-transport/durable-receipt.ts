import type { RemoteReceipt } from './remote-checkpoint.ts';
import { verifyRemoteReceipt } from './verify-remote-receipt.ts';

export type { RemoteReceipt };

export interface DurableConfirmation {
  schema: 'sg.durable-confirmation.v1';
  state: 'durable-confirmed';
  job_key: string;
  receipt: RemoteReceipt;
}

interface DurableJobPrepared {
  schema: 'sg.durable-job.v1';
  job_key: string;
  context: {
    instanceId: string;
    runtimeVersion: string;
    imageDigest: string;
    keyId: string;
  };
  record: {
    schema: 'sg.local-job.v1';
    job_id: string;
    request_digest: string;
    state: 'artifact-verified';
    artifact: {
      leaf: string;
      bytes: number;
      sha256: string;
    };
  };
  state: 'prepared';
  receipt: null;
}

interface DurableJobConfirmed {
  schema: 'sg.durable-job.v1';
  job_key: string;
  context: {
    instanceId: string;
    runtimeVersion: string;
    imageDigest: string;
    keyId: string;
  };
  record: {
    schema: 'sg.local-job.v1';
    job_id: string;
    request_digest: string;
    state: 'artifact-verified';
    artifact: {
      leaf: string;
      bytes: number;
      sha256: string;
    };
  };
  state: 'confirmed';
  receipt: RemoteReceipt;
}

type DurableJob = DurableJobPrepared | DurableJobConfirmed;

interface DurableRegistry {
  schema: 'sg.durable-registry.v1';
  jobs: DurableJob[];
}

const STORAGE_KEY = 'sg.durable-confirmations.v1';
const MAX_REGISTRY_BYTES = 1024 * 1024;
const MAX_JOB_BYTES = 8192;
const MAX_JOBS_COUNT = 256;
const TOTAL_TIMEOUT_MS = 60000;

const HEX32_RE = /^[0-9a-f]{32}$/;
const HEX64_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[a-z0-9-]{1,64}$/;
const MAX_BYTES = 64 * 1024 * 1024 + 4136;

function fail(): never {
  throw new Error('Durable checkpoint held');
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
  schema: 'sg.local-job.v1';
  job_id: string;
  request_digest: string;
  state: 'artifact-verified';
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
    schema: 'sg.local-job.v1',
    job_id,
    request_digest,
    state: 'artifact-verified',
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

async function validateDurableJob(rawJob: unknown, check: () => void, race: <T>(promise: Promise<T>) => Promise<T>): Promise<DurableJob> {
  check();
  if (!isPlainObject(rawJob)) fail();
  if (!hasExactKeys(rawJob, ['schema', 'job_key', 'context', 'record', 'state', 'receipt'])) fail();
  if (rawJob.schema !== 'sg.durable-job.v1') fail();
  if (typeof rawJob.job_key !== 'string' || !HEX64_RE.test(rawJob.job_key)) fail();
  const validatedCtx = validateContext(rawJob.context);
  const validatedRec = validateRecord(rawJob.record);

  const expectedReqObj = {
    context: {
      imageDigest: validatedCtx.imageDigest,
      instanceId: validatedCtx.instanceId,
      keyId: validatedCtx.keyId,
      runtimeVersion: validatedCtx.runtimeVersion,
    },
    operation: 'checkpoint',
    request: { job_id: validatedRec.job_id },
    schema: 'sg.operation-request.v1',
  };
  const canonicalReqJson = canonicalJson(expectedReqObj);
  const expectedReqDigest = await race(sha256Hex(new TextEncoder().encode(canonicalReqJson)));
  check();
  if (expectedReqDigest !== validatedRec.request_digest) fail();

  const jobObj = {
    context: {
      imageDigest: validatedCtx.imageDigest,
      instanceId: validatedCtx.instanceId,
      keyId: validatedCtx.keyId,
      runtimeVersion: validatedCtx.runtimeVersion,
    },
    job_id: validatedRec.job_id,
    request_digest: validatedRec.request_digest,
  };
  const canonicalJobJson = canonicalJson(jobObj);
  const computedJobKey = await race(sha256Hex(new TextEncoder().encode(canonicalJobJson)));
  check();
  if (computedJobKey !== rawJob.job_key) fail();

  const canonicalJobStr = canonicalJson(rawJob);
  const jobBytes = new TextEncoder().encode(canonicalJobStr);
  if (jobBytes.byteLength > MAX_JOB_BYTES) fail();

  const expectedObjectKey = `cp/v1/${validatedCtx.instanceId}/${validatedCtx.imageDigest}/${validatedRec.job_id}/${validatedRec.request_digest}/${validatedRec.artifact.sha256}.bin`;
  const expectedCommitKey = `cp/v1/${validatedCtx.instanceId}/${validatedCtx.imageDigest}/${validatedRec.job_id}/${validatedRec.request_digest}/${validatedRec.artifact.sha256}.commit.json`;

  if (rawJob.state === 'prepared') {
    if (rawJob.receipt !== null) fail();
    return {
      schema: 'sg.durable-job.v1',
      job_key: rawJob.job_key,
      context: validatedCtx,
      record: validatedRec,
      state: 'prepared',
      receipt: null,
    };
  } else if (rawJob.state === 'confirmed') {
    const validatedRcpt = validateExpectedReceipt(rawJob.receipt);
    if (validatedRcpt.job_id !== validatedRec.job_id) fail();
    if (validatedRcpt.request_digest !== validatedRec.request_digest) fail();
    if (validatedRcpt.context.instanceId !== validatedCtx.instanceId) fail();
    if (validatedRcpt.context.runtimeVersion !== validatedCtx.runtimeVersion) fail();
    if (validatedRcpt.context.imageDigest !== validatedCtx.imageDigest) fail();
    if (validatedRcpt.context.keyId !== validatedCtx.keyId) fail();
    if (validatedRcpt.artifact.leaf !== validatedRec.artifact.leaf) fail();
    if (validatedRcpt.artifact.bytes !== validatedRec.artifact.bytes) fail();
    if (validatedRcpt.artifact.sha256 !== validatedRec.artifact.sha256) fail();
    if (validatedRcpt.object_key !== expectedObjectKey) fail();
    if (validatedRcpt.commit_key !== expectedCommitKey) fail();
    if (validatedRcpt.object_version === validatedRcpt.commit_version) fail();
    return {
      schema: 'sg.durable-job.v1',
      job_key: rawJob.job_key,
      context: validatedCtx,
      record: validatedRec,
      state: 'confirmed',
      receipt: validatedRcpt,
    };
  } else {
    fail();
  }
}

async function parseAndValidateRegistry(rawString: unknown, check: () => void, race: <T>(promise: Promise<T>) => Promise<T>): Promise<DurableRegistry> {
  check();
  if (typeof rawString !== 'string') fail();
  const rawBytes = new TextEncoder().encode(rawString);
  if (rawBytes.byteLength > MAX_REGISTRY_BYTES) fail();

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawString);
  } catch {
    fail();
  }

  if (!isPlainObject(parsed)) fail();
  if (!hasExactKeys(parsed, ['schema', 'jobs'])) fail();
  if (parsed.schema !== 'sg.durable-registry.v1') fail();
  if (!Array.isArray(parsed.jobs)) fail();
  if (parsed.jobs.length > MAX_JOBS_COUNT) fail();

  const jobs: DurableJob[] = [];
  let prevKey = '';
  for (let i = 0; i < parsed.jobs.length; i++) {
    const j = await validateDurableJob(parsed.jobs[i], check, race);
    check();
    if (i === 0) {
      prevKey = j.job_key;
    } else {
      if (j.job_key <= prevKey) fail();
      prevKey = j.job_key;
    }
    jobs.push(j);
  }

  const validatedRegistry: DurableRegistry = {
    schema: 'sg.durable-registry.v1',
    jobs,
  };

  const canonicalRegStr = canonicalJson(validatedRegistry);
  if (canonicalRegStr !== rawString) fail();

  return validatedRegistry;
}

function serializeRegistry(registry: DurableRegistry): string {
  const sortedJobs = [...registry.jobs].sort((a, b) => (a.job_key < b.job_key ? -1 : a.job_key > b.job_key ? 1 : 0));
  for (const j of sortedJobs) {
    const jStr = canonicalJson(j);
    const jBytes = new TextEncoder().encode(jStr);
    if (jBytes.byteLength > MAX_JOB_BYTES) fail();
  }
  const reg = {
    schema: 'sg.durable-registry.v1' as const,
    jobs: sortedJobs,
  };
  const str = canonicalJson(reg);
  const bytes = new TextEncoder().encode(str);
  if (bytes.byteLength > MAX_REGISTRY_BYTES) fail();
  return str;
}

export async function confirmRemoteCheckpoint(
  storage: Pick<DurableObjectStorage, 'transaction' | 'get' | 'sync'>,
  bucket: Pick<R2Bucket, 'head' | 'get'>,
  context: object,
  localRecord: object,
  signal: AbortSignal,
  expectedReceipt?: object
): Promise<DurableConfirmation> {
  const deadline = performance.now() + TOTAL_TIMEOUT_MS;
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
  }, TOTAL_TIMEOUT_MS);

  const checkGuard = () => {
    if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) fail();
  };

  const raceDeadline = <T>(promise: Promise<T>): Promise<T> => {
    return new Promise<T>((resolve, reject) => {
      const onAbort = () => {
        abortController.signal.removeEventListener('abort', onAbort);
        reject(new Error('Durable checkpoint held'));
      };
      if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
        promise.catch(() => {});
        reject(new Error('Durable checkpoint held'));
        return;
      }
      abortController.signal.addEventListener('abort', onAbort, { once: true });
      promise.then(
        (value) => {
          abortController.signal.removeEventListener('abort', onAbort);
          if (!guardOpen || signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
            reject(new Error('Durable checkpoint held'));
          } else {
            resolve(value);
          }
        },
        (err) => {
          abortController.signal.removeEventListener('abort', onAbort);
          reject(err instanceof Error && err.message === 'Durable checkpoint held' ? err : new Error('Durable checkpoint held'));
        }
      );
    });
  };

  try {
    checkGuard();
    const ctx = validateContext(context);
    const rec = validateRecord(localRecord);
    const exp = expectedReceipt !== undefined ? validateExpectedReceipt(expectedReceipt) : null;

    const expectedObjectKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${rec.job_id}/${rec.request_digest}/${rec.artifact.sha256}.bin`;
    const expectedCommitKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${rec.job_id}/${rec.request_digest}/${rec.artifact.sha256}.commit.json`;

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
      if (exp.object_key !== expectedObjectKey) fail();
      if (exp.commit_key !== expectedCommitKey) fail();
      if (exp.object_version === exp.commit_version) fail();
    }

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
    const expectedJobObj = {
      context: {
        imageDigest: ctx.imageDigest,
        instanceId: ctx.instanceId,
        keyId: ctx.keyId,
        runtimeVersion: ctx.runtimeVersion,
      },
      job_id: rec.job_id,
      request_digest: rec.request_digest,
    };
    const canonicalJobJson = canonicalJson(expectedJobObj);
    const targetJobKey = await raceDeadline(sha256Hex(new TextEncoder().encode(canonicalJobJson)));

    checkGuard();

    // First transaction: validate/prepare slot and return stored receipt pin if confirmed
    const pinFromFirstTxn = await raceDeadline(
      storage.transaction(async (txn) => {
        checkGuard();
        const raw = await txn.get<string>(STORAGE_KEY);
        checkGuard();

        let registry: DurableRegistry;
        if (raw === undefined) {
          registry = { schema: 'sg.durable-registry.v1', jobs: [] };
        } else {
          registry = await parseAndValidateRegistry(raw, checkGuard, raceDeadline);
        }

        let foundPin: RemoteReceipt | null = null;
        const existingIdx = registry.jobs.findIndex((j) => j.job_key === targetJobKey);
        if (existingIdx >= 0) {
          const existing = registry.jobs[existingIdx];
          if (
            existing.context.instanceId !== ctx.instanceId ||
            existing.context.runtimeVersion !== ctx.runtimeVersion ||
            existing.context.imageDigest !== ctx.imageDigest ||
            existing.context.keyId !== ctx.keyId ||
            existing.record.schema !== rec.schema ||
            existing.record.job_id !== rec.job_id ||
            existing.record.request_digest !== rec.request_digest ||
            existing.record.state !== rec.state ||
            existing.record.artifact.leaf !== rec.artifact.leaf ||
            existing.record.artifact.bytes !== rec.artifact.bytes ||
            existing.record.artifact.sha256 !== rec.artifact.sha256
          ) {
            fail();
          }
          if (existing.state === 'confirmed') {
            foundPin = { ...existing.receipt, context: { ...existing.receipt.context }, artifact: { ...existing.receipt.artifact } };
          }
        } else {
          if (registry.jobs.length >= MAX_JOBS_COUNT) fail();
          const newJob: DurableJobPrepared = {
            schema: 'sg.durable-job.v1',
            job_key: targetJobKey,
            context: { ...ctx },
            record: {
              schema: 'sg.local-job.v1',
              job_id: rec.job_id,
              request_digest: rec.request_digest,
              state: 'artifact-verified',
              artifact: { ...rec.artifact },
            },
            state: 'prepared',
            receipt: null,
          };

          const newJobs = [...registry.jobs, newJob].sort((a, b) =>
            a.job_key < b.job_key ? -1 : a.job_key > b.job_key ? 1 : 0
          );
          const newRegistry: DurableRegistry = {
            schema: 'sg.durable-registry.v1',
            jobs: newJobs,
          };
          const serialized = serializeRegistry(newRegistry);
          checkGuard();
          await txn.put(STORAGE_KEY, serialized);
          checkGuard();
        }
        return foundPin;
      })
    );

    checkGuard();
    let receiptToVerifyWith: RemoteReceipt | undefined = undefined;
    if (pinFromFirstTxn !== null && exp !== null) {
      const pinStr = canonicalJson(pinFromFirstTxn);
      const expStr = canonicalJson(exp);
      if (pinStr !== expStr) fail();
      receiptToVerifyWith = pinFromFirstTxn;
    } else if (pinFromFirstTxn !== null) {
      receiptToVerifyWith = pinFromFirstTxn;
    } else if (exp !== null) {
      receiptToVerifyWith = exp;
    }

    checkGuard();
    let verifiedReceipt: RemoteReceipt;
    try {
      verifiedReceipt = await raceDeadline(
        verifyRemoteReceipt(bucket, ctx, rec, abortController.signal, receiptToVerifyWith)
      );
    } catch {
      fail();
    }

    checkGuard();
    const validatedVerifiedReceipt = validateExpectedReceipt(verifiedReceipt);

    // Second transaction: confirm slot
    await raceDeadline(
      storage.transaction(async (txn) => {
        checkGuard();
        const raw = await txn.get<string>(STORAGE_KEY);
        checkGuard();
        if (raw === undefined) fail();
        const registry = await parseAndValidateRegistry(raw, checkGuard, raceDeadline);
        const existingIdx = registry.jobs.findIndex((j) => j.job_key === targetJobKey);
        if (existingIdx < 0) fail();
        const existing = registry.jobs[existingIdx];

        if (
          existing.context.instanceId !== ctx.instanceId ||
          existing.context.runtimeVersion !== ctx.runtimeVersion ||
          existing.context.imageDigest !== ctx.imageDigest ||
          existing.context.keyId !== ctx.keyId ||
          existing.record.schema !== rec.schema ||
          existing.record.job_id !== rec.job_id ||
          existing.record.request_digest !== rec.request_digest ||
          existing.record.state !== rec.state ||
          existing.record.artifact.leaf !== rec.artifact.leaf ||
          existing.record.artifact.bytes !== rec.artifact.bytes ||
          existing.record.artifact.sha256 !== rec.artifact.sha256
        ) {
          fail();
        }

        if (existing.state === 'confirmed') {
          const existingRcptStr = canonicalJson(existing.receipt);
          const verifiedRcptStr = canonicalJson(validatedVerifiedReceipt);
          if (existingRcptStr !== verifiedRcptStr) fail();
        } else if (existing.state === 'prepared') {
          const confirmedJob: DurableJobConfirmed = {
            schema: 'sg.durable-job.v1',
            job_key: targetJobKey,
            context: { ...ctx },
            record: {
              schema: 'sg.local-job.v1',
              job_id: rec.job_id,
              request_digest: rec.request_digest,
              state: 'artifact-verified',
              artifact: { ...rec.artifact },
            },
            state: 'confirmed',
            receipt: validatedVerifiedReceipt,
          };

          const newJobs = [...registry.jobs];
          newJobs[existingIdx] = confirmedJob;
          newJobs.sort((a, b) => (a.job_key < b.job_key ? -1 : a.job_key > b.job_key ? 1 : 0));
          const newRegistry: DurableRegistry = {
            schema: 'sg.durable-registry.v1',
            jobs: newJobs,
          };
          const serialized = serializeRegistry(newRegistry);
          checkGuard();
          await txn.put(STORAGE_KEY, serialized);
          checkGuard();
        } else {
          fail();
        }
      })
    );

    checkGuard();
    await raceDeadline(storage.sync());

    checkGuard();
    const readbackRaw = await raceDeadline(storage.get<string>(STORAGE_KEY));
    if (readbackRaw === undefined) fail();
    const readbackRegistry = await raceDeadline(parseAndValidateRegistry(readbackRaw, checkGuard, raceDeadline));
    const readbackJob = readbackRegistry.jobs.find((j) => j.job_key === targetJobKey);
    if (!readbackJob || readbackJob.state !== 'confirmed') fail();

    const readbackRcptStr = canonicalJson(readbackJob.receipt);
    const verifiedRcptStr = canonicalJson(validatedVerifiedReceipt);
    if (readbackRcptStr !== verifiedRcptStr) fail();

    checkGuard();

    const confirmation: DurableConfirmation = {
      schema: 'sg.durable-confirmation.v1',
      state: 'durable-confirmed',
      job_key: targetJobKey,
      receipt: validatedVerifiedReceipt,
    };

    return confirmation;
  } catch {
    guardOpen = false;
    abortController.abort();
    fail();
  } finally {
    cleanup();
    if (signal.aborted || abortController.signal.aborted || performance.now() >= deadline) {
      fail();
    }
  }
  throw new Error('Durable checkpoint held');
}
