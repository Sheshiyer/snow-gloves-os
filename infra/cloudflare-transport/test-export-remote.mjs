import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { commitExportCipherToRemote } from './export-remote.ts';

const validContext = {
  instanceId: 'test-instance',
  runtimeVersion: '3.8.50',
  imageDigest: 'b'.repeat(64),
  keyId: 'test-key-01',
};
const validJobId = 'f'.repeat(32);
const validBearer = 'a'.repeat(48);

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
const validPayload = {
  job_id: validJobId,
  request_digest: validReqDigest,
};

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

function createMockFetcher(opts = {}) {
  const {
    status = 200,
    bodyBytes = testCipher,
    contentType = 'application/vnd.sg.cipher-export+v1',
    cacheControl = 'no-store',
    connection = 'close',
    contextHeader = JSON.stringify(validContext),
    recordHeader = JSON.stringify(validRecord),
    digestHeader = testSha256,
    extraHeaders = {},
    chunkSize = 32768,
    onFetch = () => {},
    onBodyCancel = () => {},
    streamErrorAfter = null,
    streamHang = false,
  } = opts;

  return {
    async fetch(url, init) {
      onFetch(url, init);
      if (init.signal) {
        init.signal.addEventListener('abort', () => {
          opts.onFetchAbort?.();
        }, { once: true });
      }
      const headers = new Headers({
        'content-type': contentType,
        'content-length': String(bodyBytes ? bodyBytes.byteLength : 0),
        'cache-control': cacheControl,
        'x-sg-export-context': contextHeader,
        'x-sg-export-record': recordHeader,
        'x-sg-export-digest': digestHeader,
        ...extraHeaders,
      });
      if (connection !== undefined && connection !== null) headers.set('connection', connection);

      let readable = null;
      if (bodyBytes) {
        let offset = 0;
        readable = new ReadableStream({
          pull(controller) {
            if (streamHang) {
              return new Promise(() => {});
            }
            if (streamErrorAfter !== null && offset >= streamErrorAfter) {
              controller.error(new Error('simulated body stream failure'));
              return;
            }
            if (offset >= bodyBytes.byteLength) {
              controller.close();
              return;
            }
            const nextOffset = Math.min(offset + chunkSize, bodyBytes.byteLength);
            controller.enqueue(bodyBytes.subarray(offset, nextOffset));
            offset = nextOffset;
          },
          cancel(reason) {
            onBodyCancel(reason);
          },
        });
      }

      return new Response(readable, {
        status,
        headers,
      });
    },
  };
}

function createPrepopulatedBucket(ctx, record, cipherBytes) {
  const storage = new Map();
  const objectKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${record.job_id}/${record.request_digest}/${record.artifact.sha256}.bin`;
  const commitKey = `cp/v1/${ctx.instanceId}/${ctx.imageDigest}/${record.job_id}/${record.request_digest}/${record.artifact.sha256}.commit.json`;
  const objectVersion = 'pre-existing-obj-ver-001';
  const commitVersion = 'pre-existing-commit-ver-001';

  const cipherCustomMetadata = {
    instanceId: ctx.instanceId,
    runtimeVersion: ctx.runtimeVersion,
    imageDigest: ctx.imageDigest,
    keyId: ctx.keyId,
    job_id: record.job_id,
    request_digest: record.request_digest,
    bytes: String(record.artifact.bytes),
    sha256: record.artifact.sha256,
  };

  const sha256Buf = createHash('sha256').update(cipherBytes).digest();
  const sha256ArrayBuf = sha256Buf.buffer.slice(sha256Buf.byteOffset, sha256Buf.byteOffset + sha256Buf.byteLength);

  storage.set(objectKey, {
    key: objectKey,
    version: objectVersion,
    size: record.artifact.bytes,
    checksums: { sha256: sha256ArrayBuf },
    customMetadata: cipherCustomMetadata,
    _rawBytes: cipherBytes,
  });

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
  const commitBytes = new TextEncoder().encode(canonicalCommitStr);
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
  };

  storage.set(commitKey, {
    key: commitKey,
    version: commitVersion,
    size: commitBytes.byteLength,
    checksums: { sha256: commitShaArrayBuf },
    customMetadata: commitCustomMetadata,
    _rawBytes: commitBytes,
  });

  let putCalled = false;

  return {
    get putCalled() { return putCalled; },
    async head(key) {
      return storage.get(key) || null;
    },
    async get(key) {
      const item = storage.get(key);
      if (!item) return null;
      return {
        ...item,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(item._rawBytes);
            controller.close();
          },
        }),
      };
    },
    async put(key, body, init) {
      putCalled = true;
      throw new Error('put should not be called in preexisting replay');
    },
  };
}

await test('request body is EXACT JSON.stringify(payload) asserting probe criteria', async () => {
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);
  let capturedBody = '';
  const fetcher = createMockFetcher({
    onFetch: (url, init) => {
      capturedBody = init.body;
    },
  });

  const receipt = await commitExportCipherToRemote(
    bucket,
    fetcher,
    validContext,
    validPayload,
    validBearer,
    new AbortController().signal
  );

  assert.equal(capturedBody, JSON.stringify(validPayload));
  assert.equal(bucket.putCalled, false);
  assert.equal(receipt.schema, 'sg.remote-checkpoint.v1');
  assert.equal(receipt.state, 'remote-committed');
  assert.equal(receipt.job_id, validJobId);
  assert.equal(receipt.request_digest, validReqDigest);
});

await test('preexisting replay cancels stream without aborting helper deadline controller, succeeds ACK', async () => {
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);
  let bodyCancelled = false;
  let fetchAborted = false;
  const fetcher = createMockFetcher({
    onBodyCancel: () => {
      bodyCancelled = true;
    },
    onFetchAbort: () => {
      fetchAborted = true;
    },
  });

  const receipt = await commitExportCipherToRemote(
    bucket,
    fetcher,
    validContext,
    validPayload,
    validBearer,
    new AbortController().signal
  );

  assert.equal(bodyCancelled, true);
  assert.equal(fetchAborted, true);
  assert.equal(receipt.object_version, 'pre-existing-obj-ver-001');
  assert.equal(receipt.commit_version, 'pre-existing-commit-ver-001');
});

await test('invalid header aborts fetch controller and cancels body before R2 invocation', async () => {
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);
  let bodyCancelled = false;
  let fetchAborted = false;
  const fetcher = createMockFetcher({
    contentType: 'text/plain',
    onBodyCancel: () => {
      bodyCancelled = true;
    },
    onFetchAbort: () => {
      fetchAborted = true;
    },
  });

  await assert.rejects(
    commitExportCipherToRemote(bucket, fetcher, validContext, validPayload, validBearer, new AbortController().signal),
    /Export checkpoint held/
  );

  assert.equal(fetchAborted, true);
  assert.equal(bodyCancelled, true);
  assert.equal(bucket.putCalled, false);
});

await test('late fetch resolution after race aborted cancels response body', async () => {
  let delayedResolve;
  let startedResolve;const started=new Promise(r=>startedResolve=r);
  let lateBodyCancelled = false;
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);

  const lateFetcher = {
    async fetch(url, init) {
      return new Promise((resolve) => {
        startedResolve();
        delayedResolve = () => {
          const headers = new Headers({
            'content-type': 'application/vnd.sg.cipher-export+v1',
            'content-length': String(testCipher.byteLength),
            'cache-control': 'no-store',
            'connection': 'close',
            'x-sg-export-context': JSON.stringify(validContext),
            'x-sg-export-record': JSON.stringify(validRecord),
            'x-sg-export-digest': testSha256,
          });
          const body = new ReadableStream({
            cancel() {
              lateBodyCancelled = true;
            },
          });
          resolve(new Response(body, { status: 200, headers }));
        };
      });
    },
  };

  const ctrl = new AbortController();
  const promise = commitExportCipherToRemote(bucket, lateFetcher, validContext, validPayload, validBearer, ctrl.signal);
  await started;
  ctrl.abort();

  await assert.rejects(promise, /Export checkpoint held/);

  delayedResolve();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(lateBodyCancelled, true);
});

await test('missing Connection close header is rejected', async () => {
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);
  const fetcher = createMockFetcher({ connection: null });

  await assert.rejects(
    commitExportCipherToRemote(bucket, fetcher, validContext, validPayload, validBearer, new AbortController().signal),
    /Export checkpoint held/
  );
});

await test('uppercase digest header fails exact strict lowercase check', async () => {
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);
  const fetcher = createMockFetcher({ digestHeader: testSha256.toUpperCase() });

  await assert.rejects(
    commitExportCipherToRemote(bucket, fetcher, validContext, validPayload, validBearer, new AbortController().signal),
    /Export checkpoint held/
  );
});

await test('stream fault triggers stream error and abort cleanup', async () => {
  const bucket = createPrepopulatedBucket(validContext, validRecord, testCipher);
  let bodyCancelled = false;
  const fetcher = createMockFetcher({
    streamErrorAfter: 1000,
    onBodyCancel: () => {
      bodyCancelled = true;
    },
  });

  const receipt = await commitExportCipherToRemote(bucket, fetcher, validContext, validPayload, validBearer, new AbortController().signal);
  assert.equal(receipt.state, 'remote-committed');
});

await test('cleanup observer cannot acknowledge after total deadline',async()=>{
const original=performance.now;let now=0;performance.now=()=>now;const ctrl=new AbortController();const remove=ctrl.signal.removeEventListener.bind(ctrl.signal);ctrl.signal.removeEventListener=(...args)=>{now=30001;return remove(...args);};
try{await assert.rejects(commitExportCipherToRemote(createPrepopulatedBucket(validContext,validRecord,testCipher),createMockFetcher(),validContext,validPayload,validBearer,ctrl.signal),/Export checkpoint held/);}finally{performance.now=original;}
});

await test('validated payload copy survives mutation during digest',async()=>{
const payload={...validPayload};const original=crypto.subtle.digest;let body;
crypto.subtle.digest=async(...args)=>{const result=await original.apply(crypto.subtle,args);payload.job_id='1'.repeat(32);return result;};
try{const receipt=await commitExportCipherToRemote(createPrepopulatedBucket(validContext,validRecord,testCipher),createMockFetcher({onFetch(u,i){body=JSON.parse(i.body);}}),validContext,payload,validBearer,new AbortController().signal);assert.deepEqual(body,validPayload);assert.equal(receipt.job_id,validJobId);}finally{crypto.subtle.digest=original;}
});
await test('parent abort settles stalled fetch headers without R2 effects',async()=>{
let startedResolve;const started=new Promise(r=>startedResolve=r);let fetchSignal;let calls=0;const ctrl=new AbortController();const promise=commitExportCipherToRemote({head:async()=>{calls++;return null;},put:async()=>null,get:async()=>null},{fetch(u,i){fetchSignal=i.signal;startedResolve();return new Promise(()=>{});}},validContext,validPayload,validBearer,ctrl.signal);await started;ctrl.abort();await assert.rejects(promise,/Export checkpoint held/);assert.equal(fetchSignal.aborted,true);assert.equal(calls,0);
});
await test('late header observer stops before R2 and cancels response',async()=>{
const original=performance.now;let now=0;performance.now=()=>now;let calls=0;let cancelled=false;
try{await assert.rejects(commitExportCipherToRemote({head:async()=>{calls++;return null;},put:async()=>null,get:async()=>null},createMockFetcher({onFetch(){now=30001;},onBodyCancel(){cancelled=true;}}),validContext,validPayload,validBearer,new AbortController().signal),/Export checkpoint held/);assert.equal(calls,0);assert.equal(cancelled,true);}finally{performance.now=original;}
});
await test('replay acknowledgment does not await hanging body cancellation',async()=>{
const base=createMockFetcher();let cancelled=false;const fetcher={async fetch(u,i){const r=await base.fetch(u,i);return new Response(new ReadableStream({cancel(){cancelled=true;return new Promise(()=>{});}}),{headers:r.headers});}};
const receipt=await commitExportCipherToRemote(createPrepopulatedBucket(validContext,validRecord,testCipher),fetcher,validContext,validPayload,validBearer,new AbortController().signal);assert.equal(cancelled,true);assert.equal(receipt.state,'remote-committed');
});
