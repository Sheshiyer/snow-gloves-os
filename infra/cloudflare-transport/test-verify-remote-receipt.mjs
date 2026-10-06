import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { verifyRemoteReceipt } from './verify-remote-receipt.ts';
import { commitRemoteCheckpoint } from './remote-checkpoint.ts';

const validContext = {
  instanceId: 'test-instance',
  runtimeVersion: '3.8.50',
  imageDigest: 'b'.repeat(64),
  keyId: 'test-key-01',
};
const validJobId = 'f'.repeat(32);

function makeCanonicalReqDigest(ctx, jobId) {
  const reqObj = {
    context: {
      imageDigest: ctx.imageDigest,
      instanceId: ctx.instanceId,
      keyId: ctx.keyId,
      runtimeVersion: ctx.runtimeVersion,
    },
    operation: 'checkpoint',
    request: { job_id: jobId },
    schema: 'sg.operation-request.v1',
  };
  const keys = Object.keys(reqObj).sort();
  const canonicalJson = '{' + keys.map(k => JSON.stringify(k) + ':' + (typeof reqObj[k] === 'object' ? '{' + Object.keys(reqObj[k]).sort().map(sk => JSON.stringify(sk) + ':' + JSON.stringify(reqObj[k][sk])).join(',') + '}' : JSON.stringify(reqObj[k]))).join(',') + '}';
  return createHash('sha256').update(canonicalJson).digest('hex');
}

function canonicalJsonStr(obj) {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(canonicalJsonStr).join(',') + ']';
  }
  const keys = Object.keys(obj).sort();
  const entries = keys.map((k) => JSON.stringify(k) + ':' + canonicalJsonStr(obj[k]));
  return '{' + entries.join(',') + '}';
}

const validReqDigest = makeCanonicalReqDigest(validContext, validJobId);

const testCipher = new Uint8Array(100000);
for (let i = 0; i < testCipher.length; i++) testCipher[i] = i % 251;
const testSha256 = createHash('sha256').update(testCipher).digest('hex');

const validRecord = {
  schema: 'sg.local-job.v1',
  job_id: validJobId,
  request_digest: validReqDigest,
  state: 'artifact-verified',
  artifact: {
    leaf: `sg-encrypted-${validJobId}.bin`,
    bytes: testCipher.byteLength,
    sha256: testSha256,
  },
};

function createMockStorage(ctx = validContext, record = validRecord, cipherBytes = testCipher, opts = {}) {
  const storage = new Map();
  const objectKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${record.job_id}/${record.request_digest}/${record.artifact.sha256}.bin`;
  const commitKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${record.job_id}/${record.request_digest}/${record.artifact.sha256}.commit.json`;
  const objectVersion = opts.objectVersion ?? 'obj-ver-001';
  const commitVersion = opts.commitVersion ?? 'commit-ver-001';

  const cipherCustomMetadata = {
    instanceId: ctx.instanceId,
    runtimeVersion: ctx.runtimeVersion,
    imageDigest: ctx.imageDigest,
    keyId: ctx.keyId,
    job_id: record.job_id,
    request_digest: record.request_digest,
    bytes: String(record.artifact.bytes),
    sha256: record.artifact.sha256,
    ...opts.overrideCipherMeta,
  };

  const sha256Buf = createHash('sha256').update(cipherBytes).digest();
  const sha256ArrayBuf = sha256Buf.buffer.slice(sha256Buf.byteOffset, sha256Buf.byteOffset + sha256Buf.byteLength);

  if (opts.includeCipher !== false) {
    storage.set(objectKey, {
      key: objectKey,
      version: objectVersion,
      size: opts.cipherSize ?? record.artifact.bytes,
      checksums: { sha256: opts.cipherChecksum ?? sha256ArrayBuf },
      customMetadata: cipherCustomMetadata,
      _rawBytes: cipherBytes,
    });
  }

  const commitPayload = {
    artifact: {
      bytes: record.artifact.bytes,
      leaf: record.artifact.leaf,
      sha256: record.artifact.sha256,
    },
    context: {
      imageDigest: ctx.imageDigest,
      instanceId: ctx.instanceId,
      keyId: ctx.keyId,
      runtimeVersion: ctx.runtimeVersion,
    },
    job_id: record.job_id,
    object_key: objectKey,
    object_version: objectVersion,
    request_digest: record.request_digest,
    schema: 'sg.commit-record.v1',
  };
  const canonicalCommitStr = canonicalJsonStr(commitPayload);
  let commitBytes = new TextEncoder().encode(canonicalCommitStr);
  if (opts.corruptCommitBytes) {
    commitBytes = opts.corruptCommitBytes;
  }
  const commitShaBuf = createHash('sha256').update(commitBytes).digest();
  const commitShaArrayBuf = commitShaBuf.buffer.slice(commitShaBuf.byteOffset, commitShaBuf.byteOffset + commitShaBuf.byteLength);

  const commitCustomMetadata = {
    kind: 'commit',
    runtimeVersion: ctx.runtimeVersion,
    imageDigest: ctx.imageDigest,
    keyId: ctx.keyId,
    instanceId: ctx.instanceId,
    job_id: record.job_id,
    request_digest: record.request_digest,
    object_version: objectVersion,
    ...opts.overrideCommitMeta,
  };

  if (opts.includeCommit !== false) {
    storage.set(commitKey, {
      key: commitKey,
      version: commitVersion,
      size: opts.commitSize ?? commitBytes.byteLength,
      checksums: { sha256: opts.commitChecksum ?? commitShaArrayBuf },
      customMetadata: commitCustomMetadata,
      _rawBytes: commitBytes,
    });
  }

  let cipherHeadCount = 0;
  let commitHeadCount = 0;
  let commitGetCount = 0;

  return {
    storage,
    objectKey,
    commitKey,
    objectVersion,
    commitVersion,
    get cipherHeadCount() { return cipherHeadCount; },
    get commitHeadCount() { return commitHeadCount; },
    get commitGetCount() { return commitGetCount; },
    async head(key) {
      if (key === objectKey) {
        cipherHeadCount++;
        if (opts.onCipherHead) opts.onCipherHead(cipherHeadCount);
      } else if (key === commitKey) {
        commitHeadCount++;
        if (opts.onCommitHead) opts.onCommitHead(commitHeadCount);
      }
      return storage.get(key) || null;
    },
    async get(key) {
      if (key === commitKey) {
        commitGetCount++;
        if (opts.onCommitGet) opts.onCommitGet(commitGetCount);
      }
      const item = storage.get(key);
      if (!item) return null;
      let body = item._rawBytes;
      if (opts.customGetStream) {
        return {
          ...item,
          body: opts.customGetStream(item),
        };
      }
      return {
        ...item,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(body);
            controller.close();
          },
          cancel(reason) {
            if (opts.onBodyCancel) opts.onBodyCancel(reason);
          },
        }),
      };
    },
  };
}

function makeValidReceipt(storageObj) {
  return {
    schema: 'sg.remote-checkpoint.v1',
    state: 'remote-committed',
    context: { ...validContext },
    job_id: validJobId,
    request_digest: validReqDigest,
    artifact: { ...validRecord.artifact },
    object_key: storageObj.objectKey,
    object_version: storageObj.objectVersion,
    commit_key: storageObj.commitKey,
    commit_version: storageObj.commitVersion,
  };
}

await test('identity verifyRemoteReceipt succeeds and returns fresh verified receipt', async () => {
  const bucket = createMockStorage();
  const receipt = await verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal);
  assert.equal(receipt.schema, 'sg.remote-checkpoint.v1');
  assert.equal(receipt.state, 'remote-committed');
  assert.equal(receipt.job_id, validJobId);
  assert.equal(receipt.request_digest, validReqDigest);
  assert.equal(receipt.object_version, 'obj-ver-001');
  assert.equal(receipt.commit_version, 'commit-ver-001');
  assert.equal(bucket.cipherHeadCount, 2);
  assert.equal(bucket.commitGetCount, 1);
  assert.equal(bucket.commitHeadCount, 1);
});

await test('pinned expectedReceipt match succeeds', async () => {
  const bucket = createMockStorage();
  const expected = makeValidReceipt(bucket);
  const receipt = await verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal, expected);
  assert.deepEqual(receipt, expected);
});

await test('pinned expectedReceipt version mismatch rejects', async () => {
  const bucket = createMockStorage();
  const expected = makeValidReceipt(bucket);
  expected.commit_version = 'wrong-version';
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal, expected),
    /Remote receipt held/
  );
});

await test('expectedReceipt extra top field rejects before R2', async () => {
  const bucket = createMockStorage();
  const expected = { ...makeValidReceipt(bucket), extra: 123 };
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal, expected),
    /Remote receipt held/
  );
  assert.equal(bucket.cipherHeadCount, 0);
});

await test('mutation of input copy before await does not affect verification', async () => {
  const bucket = createMockStorage();
  const ctxCopy = { ...validContext };
  const recCopy = JSON.parse(JSON.stringify(validRecord));
  const expected = makeValidReceipt(bucket);

  const origDigest = crypto.subtle.digest;
  crypto.subtle.digest = async (...args) => {
    const res = await origDigest.apply(crypto.subtle, args);
    ctxCopy.instanceId = 'mutated';
    recCopy.job_id = '0'.repeat(32);
    expected.job_id = '0'.repeat(32);
    return res;
  };

  try {
    const receipt = await verifyRemoteReceipt(bucket, ctxCopy, recCopy, new AbortController().signal, expected);
    assert.equal(receipt.job_id, validJobId);
    assert.equal(receipt.context.instanceId, validContext.instanceId);
  } finally {
    crypto.subtle.digest = origDigest;
  }
});

await test('missing cipher object returns held', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, { includeCipher: false });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('missing commit object returns held', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, { includeCommit: false });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('wrong cipher metadata returns held', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    overrideCipherMeta: { keyId: 'wrong-key' },
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('wrong commit metadata returns held', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    overrideCommitMeta: { runtimeVersion: '3.8.49' },
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('canonical commit body mismatch returns held', async () => {
  const corrupt = new TextEncoder().encode(JSON.stringify({ schema: 'tampered' }));
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    corruptCommitBytes: corrupt,
    commitSize: corrupt.byteLength,
    commitChecksum: createHash('sha256').update(corrupt).digest().buffer,
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('oversized commit body stream aborts and holds', async () => {
  const oversized = new Uint8Array(2050);
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    customGetStream: () => new ReadableStream({
      start(controller) {
        controller.enqueue(oversized);
        controller.close();
      },
    }),
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('commit version equals cipher version is rejected', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    objectVersion: 'identical-ver',
    commitVersion: 'identical-ver',
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('final head cipher version replacement interleaving is detected and held', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    onCipherHead: (count) => {
      if (count === 2) {
        const item = bucket.storage.get(bucket.objectKey);
        item.version = 'admin-replaced-ver';
      }
    },
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('final head commit replacement interleaving is detected and held', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    onCommitHead: (count) => {
      if (count === 1) {
        const item = bucket.storage.get(bucket.commitKey);
        item.version = 'admin-replaced-commit';
      }
    },
  });
  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, new AbortController().signal),
    /Remote receipt held/
  );
});

await test('late body resolution after abort is cancelled without false ACK', async () => {
  let bodyCancelled = false;
  const ctrl = new AbortController();
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    customGetStream: () => new ReadableStream({
      pull(controller) {
        ctrl.abort();
        controller.enqueue(new Uint8Array(10));
      },
      cancel() {
        bodyCancelled = true;
      },
    }),
  });

  await assert.rejects(
    verifyRemoteReceipt(bucket, validContext, validRecord, ctrl.signal),
    /Remote receipt held/
  );
  assert.equal(bodyCancelled, true);
});

await test('cleanup observer cannot acknowledge after total deadline', async () => {
  const original = performance.now;
  let now = 0;
  performance.now = () => now;
  const ctrl = new AbortController();
  const remove = ctrl.signal.removeEventListener.bind(ctrl.signal);
  ctrl.signal.removeEventListener = (...args) => {
    now = 30001;
    return remove(...args);
  };
  try {
    await assert.rejects(
      verifyRemoteReceipt(createMockStorage(), validContext, validRecord, ctrl.signal),
      /Remote receipt held/
    );
  } finally {
    performance.now = original;
  }
});

await test('actual writer replay to verifier identity and pinned readback',async()=>{
const bucket=createMockStorage();const receipt=await commitRemoteCheckpoint(bucket,validContext,validRecord,new ReadableStream(),new AbortController().signal);const verified=await verifyRemoteReceipt(bucket,validContext,validRecord,new AbortController().signal,receipt);assert.deepEqual(verified,receipt);
});

await test('invalid commit metadata cancels owned returned body',async()=>{
let cancelled=false;const bucket=createMockStorage(validContext,validRecord,testCipher,{overrideCommitMeta:{kind:'wrong'},customGetStream(){return new ReadableStream({cancel(){cancelled=true;}});}});await assert.rejects(verifyRemoteReceipt(bucket,validContext,validRecord,new AbortController().signal),/Remote receipt held/);assert.equal(cancelled,true);
});
await test('parent abort from cleanup observer cannot produce ACK',async()=>{
const ctrl=new AbortController();const remove=ctrl.signal.removeEventListener.bind(ctrl.signal);ctrl.signal.removeEventListener=(...args)=>{ctrl.abort();return remove(...args);};await assert.rejects(verifyRemoteReceipt(createMockStorage(),validContext,validRecord,ctrl.signal),/Remote receipt held/);
});

await test('late get result after cancellation is contained and body is canceled',async()=>{
const base=createMockStorage();let startedResolve;const started=new Promise(r=>startedResolve=r);let finish;let cancelled=false;const ctrl=new AbortController();const bucket={head:base.head.bind(base),get:()=>{startedResolve();return new Promise(r=>finish=r);}};
const promise=verifyRemoteReceipt(bucket,validContext,validRecord,ctrl.signal);await started;ctrl.abort();await assert.rejects(promise,/Remote receipt held/);const obj=base.storage.get(base.commitKey);finish({...obj,body:new ReadableStream({cancel(){cancelled=true;}})});await new Promise(r=>setTimeout(r,10));assert.equal(cancelled,true);
});
await test('late get body getter fault does not escape terminal boundary',async()=>{
const base=createMockStorage();let startedResolve;const started=new Promise(r=>startedResolve=r);let finish;const ctrl=new AbortController();const bucket={head:base.head.bind(base),get:()=>{startedResolve();return new Promise(r=>finish=r);}};const promise=verifyRemoteReceipt(bucket,validContext,validRecord,ctrl.signal);await started;ctrl.abort();await assert.rejects(promise,/Remote receipt held/);finish({get body(){throw Error('OWNED DIAGNOSTIC');}});await new Promise(r=>setTimeout(r,20));
});
