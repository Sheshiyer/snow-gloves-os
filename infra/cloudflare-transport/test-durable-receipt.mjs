import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { confirmRemoteCheckpoint } from './durable-receipt.ts';
import { verifyRemoteReceipt } from './verify-remote-receipt.ts';

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
  return createHash('sha256').update(canonicalJsonStr(reqObj)).digest('hex');
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

function computeJobKey(ctx, jobId, reqDigest) {
  const jobObj = {
    context: {
      imageDigest: ctx.imageDigest,
      instanceId: ctx.instanceId,
      keyId: ctx.keyId,
      runtimeVersion: ctx.runtimeVersion,
    },
    job_id: jobId,
    request_digest: reqDigest,
  };
  return createHash('sha256').update(canonicalJsonStr(jobObj)).digest('hex');
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
      if (opts.inTransactionAssertion && opts.inTransactionAssertion()) {
        throw new Error('R2 called inside transaction');
      }
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
      if (opts.inTransactionAssertion && opts.inTransactionAssertion()) {
        throw new Error('R2 called inside transaction');
      }
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

function createMockDOStorage(initialMap = new Map()) {
  const store = new Map(initialMap);
  let syncCalls = 0;
  let getCalls = 0;
  let putCalls = 0;
  let activeTransactions = 0;
  let queue = Promise.resolve();

  return {
    store,
    get syncCalls() { return syncCalls; },
    get getCalls() { return getCalls; },
    get putCalls() { return putCalls; },
    get isInsideTransaction() { return activeTransactions > 0; },
    async get(key) {
      getCalls++;
      return store.get(key);
    },
    async put(key, val) {
      putCalls++;
      store.set(key, val);
    },
    async sync() {
      syncCalls++;
    },
    async transaction(closure) {
      const run = async () => {
        activeTransactions++;
        const staging = new Map(store);
        const txn = {
          async get(k) {
            return staging.get(k);
          },
          async put(k, v) {
            staging.set(k, v);
          },
          rollback() {
            throw new Error('Rollback');
          },
        };
        try {
          const res = await closure(txn);
          for (const [k, v] of staging) {
            store.set(k, v);
          }
          return res;
        } finally {
          activeTransactions--;
        }
      };
      const next = queue.then(run, run);
      queue = next.catch(() => {});
      return next;
    },
  };
}

await test('fresh undefined root creates prepared slot, completes confirmation and returns stable receipt', async () => {
  const doStorage = createMockDOStorage();
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    inTransactionAssertion: () => doStorage.isInsideTransaction,
  });
  const expectedJobKey = computeJobKey(validContext, validJobId, validReqDigest);

  const conf = await confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal);
  assert.equal(conf.schema, 'sg.durable-confirmation.v1');
  assert.equal(conf.state, 'durable-confirmed');
  assert.equal(conf.job_key, expectedJobKey);
  assert.equal(conf.receipt.schema, 'sg.remote-checkpoint.v1');
  assert.equal(conf.receipt.state, 'remote-committed');
  assert.equal(conf.receipt.object_version, 'obj-ver-001');

  const regRaw = doStorage.store.get('sg.durable-confirmations.v1');
  assert.ok(regRaw);
  const parsed = JSON.parse(regRaw);
  assert.equal(parsed.schema, 'sg.durable-registry.v1');
  assert.equal(parsed.jobs.length, 1);
  assert.equal(parsed.jobs[0].state, 'confirmed');
  assert.equal(parsed.jobs[0].job_key, expectedJobKey);
});

await test('replay of confirmed job independently reverifies R2 and returns confirmation without mutating peers', async () => {
  const doStorage = createMockDOStorage();
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    inTransactionAssertion: () => doStorage.isInsideTransaction,
  });
  const expectedJobKey = computeJobKey(validContext, validJobId, validReqDigest);

  const conf1 = await confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal);
  assert.equal(conf1.job_key, expectedJobKey);

  const conf2 = await confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal);
  assert.deepEqual(conf1, conf2);
  assert.equal(bucket.cipherHeadCount, 4);
});

await test('replay with changed artifact rejects before R2', async () => {
  const doStorage = createMockDOStorage();
  const bucket = createMockStorage();
  await confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal);

  const changedRecord = {
    ...validRecord,
    artifact: {
      ...validRecord.artifact,
      sha256: 'a'.repeat(64),
    },
  };

  const initialHeadCount = bucket.cipherHeadCount;
  await assert.rejects(
    confirmRemoteCheckpoint(doStorage, bucket, validContext, changedRecord, new AbortController().signal),
    /Durable checkpoint held/
  );
  assert.equal(bucket.cipherHeadCount, initialHeadCount);
});

await test('capacity bound 256: new job rejected if full, existing job can still resume', async () => {
  const doStorage = createMockDOStorage();
  const fullJobs = [];
  let existingRecord = null;
  let existingCipher = null;
  for (let i = 0; i < 256; i++) {
    const jobId = i.toString(16).padStart(32, '0');
    const reqDigest = makeCanonicalReqDigest(validContext, jobId);
    const jobKey = computeJobKey(validContext, jobId, reqDigest);
    const cipherBytes = new Uint8Array(100);
    cipherBytes[0] = i;
    const cipherSha = createHash('sha256').update(cipherBytes).digest('hex');
    const rec = {
      schema: 'sg.local-job.v1',
      job_id: jobId,
      request_digest: reqDigest,
      state: 'artifact-verified',
      artifact: {
        leaf: `sg-encrypted-${jobId}.bin`,
        bytes: 100,
        sha256: cipherSha,
      },
    };
    if (i === 0) {
      existingRecord = rec;
      existingCipher = cipherBytes;
    }
    fullJobs.push({
      schema: 'sg.durable-job.v1',
      job_key: jobKey,
      context: { ...validContext },
      record: rec,
      state: 'prepared',
      receipt: null,
    });
  }
  fullJobs.sort((a, b) => (a.job_key < b.job_key ? -1 : a.job_key > b.job_key ? 1 : 0));
  const registryStr = canonicalJsonStr({ schema: 'sg.durable-registry.v1', jobs: fullJobs });
  doStorage.store.set('sg.durable-confirmations.v1', registryStr);

  // 257th job fails before R2
  const newJobId = 'e'.repeat(32);
  const newReqDigest = makeCanonicalReqDigest(validContext, newJobId);
  const newRecord = {
    schema: 'sg.local-job.v1',
    job_id: newJobId,
    request_digest: newReqDigest,
    state: 'artifact-verified',
    artifact: {
      leaf: `sg-encrypted-${newJobId}.bin`,
      bytes: testCipher.byteLength,
      sha256: testSha256,
    },
  };
  const bucketNew = createMockStorage(validContext, newRecord);
  await assert.rejects(
    confirmRemoteCheckpoint(doStorage, bucketNew, validContext, newRecord, new AbortController().signal),
    /Durable checkpoint held/
  );

  // Existing 0th prepared job can successfully resume and confirm
  const bucketExisting = createMockStorage(validContext, existingRecord, existingCipher);
  const conf = await confirmRemoteCheckpoint(doStorage, bucketExisting, validContext, existingRecord, new AbortController().signal);
  assert.equal(conf.job_key, computeJobKey(validContext, existingRecord.job_id, existingRecord.request_digest));
  assert.equal(conf.state, 'durable-confirmed');
});

await test('abort during R2 verify leaves prepared slot in storage and does not false ACK', async () => {
  const ctrl = new AbortController();
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    onCipherHead: () => {
      ctrl.abort();
    },
  });
  const doStorage = createMockDOStorage();

  await assert.rejects(
    confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, ctrl.signal),
    /Durable checkpoint held/
  );

  const regRaw = doStorage.store.get('sg.durable-confirmations.v1');
  assert.ok(regRaw);
  const parsed = JSON.parse(regRaw);
  assert.equal(parsed.jobs.length, 1);
  assert.equal(parsed.jobs[0].state, 'prepared');
});

await test('non-canonical / corrupt registry string rejects immediately before effects', async () => {
  const doStorage = createMockDOStorage();
  doStorage.store.set('sg.durable-confirmations.v1', '{ "schema": "sg.durable-registry.v1", "jobs": [] }');
  const bucket = createMockStorage();

  await assert.rejects(
    confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal),
    /Durable checkpoint held/
  );
});

await test('stored job with forged job_key or invalid receipt bindings rejected on registry parse', async () => {
  const doStorage = createMockDOStorage();
  const forgedJob = {
    schema: 'sg.durable-job.v1',
    job_key: '0'.repeat(64),
    context: { ...validContext },
    record: { ...validRecord },
    state: 'prepared',
    receipt: null,
  };
  const regStr = canonicalJsonStr({ schema: 'sg.durable-registry.v1', jobs: [forgedJob] });
  doStorage.store.set('sg.durable-confirmations.v1', regStr);
  const bucket = createMockStorage();

  await assert.rejects(
    confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal),
    /Durable checkpoint held/
  );
});

await test('expectedReceipt context mismatch rejects BEFORE storage effects and leaves 0 jobs', async () => {
  const doStorage = createMockDOStorage();
  const bucket = createMockStorage();
  const badReceipt = {
    schema: 'sg.remote-checkpoint.v1',
    state: 'remote-committed',
    context: { ...validContext, instanceId: 'different-instance' },
    job_id: validRecord.job_id,
    request_digest: validRecord.request_digest,
    artifact: { ...validRecord.artifact },
    object_key: bucket.objectKey,
    object_version: 'obj-ver-001',
    commit_key: bucket.commitKey,
    commit_version: 'commit-ver-001',
  };

  await assert.rejects(
    confirmRemoteCheckpoint(doStorage, bucket, validContext, validRecord, new AbortController().signal, badReceipt),
    /Durable checkpoint held/
  );
  assert.equal(doStorage.store.get('sg.durable-confirmations.v1'), undefined);
});

await test('concurrent 2 distinct jobs run through serialized storage queue without losing either job', async () => {
  const doStorage = createMockDOStorage();
  const jobId1 = '1'.repeat(32);
  const reqDigest1 = makeCanonicalReqDigest(validContext, jobId1);
  const record1 = {
    schema: 'sg.local-job.v1',
    job_id: jobId1,
    request_digest: reqDigest1,
    state: 'artifact-verified',
    artifact: { leaf: `sg-encrypted-${jobId1}.bin`, bytes: 100, sha256: createHash('sha256').update(new Uint8Array(100).fill(1)).digest('hex') },
  };
  const bucket1 = createMockStorage(validContext, record1, new Uint8Array(100).fill(1));

  const jobId2 = '2'.repeat(32);
  const reqDigest2 = makeCanonicalReqDigest(validContext, jobId2);
  const record2 = {
    schema: 'sg.local-job.v1',
    job_id: jobId2,
    request_digest: reqDigest2,
    state: 'artifact-verified',
    artifact: { leaf: `sg-encrypted-${jobId2}.bin`, bytes: 200, sha256: createHash('sha256').update(new Uint8Array(200).fill(2)).digest('hex') },
  };
  const bucket2 = createMockStorage(validContext, record2, new Uint8Array(200).fill(2));

  const combinedBucket = {
    async head(k) {
      return (await bucket1.head(k)) || (await bucket2.head(k));
    },
    async get(k) {
      return (await bucket1.get(k)) || (await bucket2.get(k));
    },
  };

  const [conf1, conf2] = await Promise.all([
    confirmRemoteCheckpoint(doStorage, combinedBucket, validContext, record1, new AbortController().signal),
    confirmRemoteCheckpoint(doStorage, combinedBucket, validContext, record2, new AbortController().signal),
  ]);

  assert.notEqual(conf1.job_key, conf2.job_key);
  const regRaw = doStorage.store.get('sg.durable-confirmations.v1');
  const parsed = JSON.parse(regRaw);
  assert.equal(parsed.jobs.length, 2);
  assert.equal(parsed.jobs[0].state, 'confirmed');
  assert.equal(parsed.jobs[1].state, 'confirmed');
});

await test('registry hashing stops after abort while digest is pending', async () => {
 const storage=createMockDOStorage();
 const bucket=createMockStorage();
 await confirmRemoteCheckpoint(storage,bucket,validContext,validRecord,new AbortController().signal);
 const original=crypto.subtle.digest.bind(crypto.subtle);
 let calls=0, release, started;
 const begun=new Promise(r=>started=r);
 crypto.subtle.digest=async (...args)=>{ calls++; if(calls===3){started(); await new Promise(r=>release=r);} return original(...args); };
 const ctrl=new AbortController();
 try {
  const pending=confirmRemoteCheckpoint(storage,bucket,validContext,validRecord,ctrl.signal);
  await begun; ctrl.abort(); await assert.rejects(pending); const atAbort=calls; release();
  await new Promise(r=>setTimeout(r,30));
  assert.equal(calls,atAbort,'additional digest started after cancelled registry validation');
 } finally { crypto.subtle.digest=original; release?.(); }
});

for (const seam of ['transaction','sync','get']) await test(`storage ${seam} failure returns generic hold`,async()=>{
 const storage=createMockDOStorage();storage[seam]=async()=>{throw new Error('OWNED-DIAGNOSTIC');};
 await assert.rejects(confirmRemoteCheckpoint(storage,createMockStorage(),validContext,validRecord,new AbortController().signal),{message:'Durable checkpoint held'});
});
await test('abort during pending sync cannot return acknowledgment',async()=>{
 const storage=createMockDOStorage();const ctrl=new AbortController();let started;
 const begun=new Promise(r=>started=r);storage.sync=()=>{started();return new Promise(()=>{});};
 const p=confirmRemoteCheckpoint(storage,createMockStorage(),validContext,validRecord,ctrl.signal);await begun;ctrl.abort();
 await assert.rejects(p,{message:'Durable checkpoint held'});
 assert.equal(JSON.parse(storage.store.get('sg.durable-confirmations.v1')).jobs[0].state,'confirmed');
});
await test('missing registry between transactions is held without recreation',async()=>{
 const storage=createMockDOStorage();let n=0;const original=storage.transaction.bind(storage);
 storage.transaction=(cb)=>{if(++n===2)storage.store.delete('sg.durable-confirmations.v1');return original(cb);};
 await assert.rejects(confirmRemoteCheckpoint(storage,createMockStorage(),validContext,validRecord,new AbortController().signal),{message:'Durable checkpoint held'});
 assert.equal(storage.store.has('sg.durable-confirmations.v1'),false);
});
await test('R2 reads occur outside all storage transactions',async()=>{
 const storage=createMockDOStorage();const bucket=createMockStorage();for(const seam of ['head','get']){const f=bucket[seam].bind(bucket);bucket[seam]=(...a)=>{assert.equal(storage.isInsideTransaction,false);return f(...a);};}
 await confirmRemoteCheckpoint(storage,bucket,validContext,validRecord,new AbortController().signal);
});

await test('final cleanup abort denies otherwise verified confirmation',async()=>{
 const ctrl=new AbortController();const remove=ctrl.signal.removeEventListener.bind(ctrl.signal);
 ctrl.signal.removeEventListener=(...a)=>{remove(...a);ctrl.abort();};
 await assert.rejects(confirmRemoteCheckpoint(createMockDOStorage(),createMockStorage(),validContext,validRecord,ctrl.signal),{message:'Durable checkpoint held'});
});
await test('shared deadline includes storage sync completion',async()=>{
 const saved=Object.getOwnPropertyDescriptor(performance,'now');const original=performance.now.bind(performance);let advanced=false;
 Object.defineProperty(performance,'now',{configurable:true,value:()=>original()+(advanced?60001:0)});
 const storage=createMockDOStorage();storage.sync=async()=>{advanced=true;};
 try {await assert.rejects(confirmRemoteCheckpoint(storage,createMockStorage(),validContext,validRecord,new AbortController().signal),{message:'Durable checkpoint held'});}finally{if(saved)Object.defineProperty(performance,'now',saved);else delete performance.now;}
});
for(const mutation of ['duplicate','unsorted','request-digest','receipt-binding']) await test(`stored ${mutation} corruption is held without R2 reads`,async()=>{
 const storage=createMockDOStorage();const bucket=createMockStorage();await confirmRemoteCheckpoint(storage,bucket,validContext,validRecord,new AbortController().signal);
 const key='sg.durable-confirmations.v1';const registry=JSON.parse(storage.store.get(key));
 if(mutation==='duplicate')registry.jobs.push(structuredClone(registry.jobs[0]));
 if(mutation==='unsorted'){const other=structuredClone(registry.jobs[0]);other.job_key='0'.repeat(64);registry.jobs.push(other);}
 if(mutation==='request-digest')registry.jobs[0].record.request_digest='0'.repeat(64);
 if(mutation==='receipt-binding')registry.jobs[0].receipt.context.keyId='other-key';
 const text=canonicalJsonStr(registry);storage.store.set(key,text);const before=bucket.cipherHeadCount;
 await assert.rejects(confirmRemoteCheckpoint(storage,bucket,validContext,validRecord,new AbortController().signal),{message:'Durable checkpoint held'});
 assert.equal(storage.store.get(key),text);assert.equal(bucket.cipherHeadCount,before);
});
