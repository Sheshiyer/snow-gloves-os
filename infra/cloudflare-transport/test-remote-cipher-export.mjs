import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { openRemoteCipherExport } from './remote-cipher-export.ts';
import { commitRemoteCheckpoint } from './remote-checkpoint.ts';
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
  const keys = Object.keys(reqObj).sort();
  const canonicalJson = '{' + keys.map(k => JSON.stringify(k) + ':' + (typeof reqObj[k] === 'object' ? '{' + Object.keys(reqObj[k]).sort().map(sk => JSON.stringify(sk) + ':' + JSON.stringify(reqObj[k][sk])).join(',') + '}' : JSON.stringify(reqObj[k]))).join(',') + '}';
  return createHash('sha256').update(canonicalJson).digest('hex');
}

function canonicalJsonStr(obj) {
  if (obj === null || typeof obj !== 'object') return JSON.stringify(obj);
  if (Array.isArray(obj)) return '[' + obj.map(canonicalJsonStr).join(',') + ']';
  const keys = Object.keys(obj).sort();
  const entries = keys.map(k => JSON.stringify(k) + ':' + canonicalJsonStr(obj[k]));
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
  let cipherGetCount = 0;
  let commitHeadCount = 0;
  let commitGetCount = 0;

  return {
    storage,
    objectKey,
    commitKey,
    objectVersion,
    commitVersion,
    get cipherHeadCount() { return cipherHeadCount; },
    get cipherGetCount() { return cipherGetCount; },
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
      if (key === objectKey) {
        cipherGetCount++;
        if (opts.onCipherGet) opts.onCipherGet(cipherGetCount);
      }
      if (key === commitKey) {
        commitGetCount++;
        if (opts.onCommitGet) opts.onCommitGet(commitGetCount);
      }
      const item = storage.get(key);
      if (!item) return null;
      let body = item._rawBytes;
      if (opts.customCipherGetStream && key === objectKey) {
        return {
          ...item,
          body: opts.customCipherGetStream(item),
        };
      }
      if (opts.customGetStream && key === commitKey) {
        return {
          ...item,
          body: opts.customGetStream(item),
        };
      }
      return {
        ...item,
        body: new ReadableStream({
          start(controller) {
            if (opts.cipherChunkSlices && key === objectKey) {
              for (const slice of opts.cipherChunkSlices) {
                controller.enqueue(slice);
              }
            } else {
              controller.enqueue(body);
            }
            controller.close();
          },
          cancel(reason) {
            if (key === objectKey && opts.onCipherBodyCancel) {
              opts.onCipherBodyCancel(reason);
            }
            if (key === commitKey && opts.onBodyCancel) {
              opts.onBodyCancel(reason);
            }
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

async function consumeStreamToHash(stream) {
  const reader = stream.getReader();
  const hash = createHash('sha256');
  let bytesRead = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    assert.ok(value.byteLength <= 65536, 'Chunks emitted to receiver must be bounded by 65536');
    hash.update(value);
    bytesRead += value.byteLength;
  }
  return { bytesRead, sha256: hash.digest('hex') };
}

await test('valid export produces bounded chunks, matching SHA and receipt', async () => {
  const bucket = createMockStorage();
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  assert.equal(exportRes.schema, 'sg.remote-cipher-export.v1');
  assert.deepEqual(exportRes.receipt, pin);

  const { bytesRead, sha256 } = await consumeStreamToHash(exportRes.body);
  assert.equal(bytesRead, validRecord.artifact.bytes);
  assert.equal(sha256, validRecord.artifact.sha256);
  assert.equal(bucket.cipherGetCount, 1);
});

await test('receipt metadata returned is not ACK of consumer integrity until stream finishes', async () => {
  const bucket = createMockStorage();
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  assert.equal(exportRes.schema, 'sg.remote-cipher-export.v1');
  assert.deepEqual(exportRes.receipt, pin);
  await exportRes.body.cancel();
});

await test('input objects mutated after invocation do not alter pinned execution', async () => {
  const bucket = createMockStorage();
  const ctx = { ...validContext };
  const rec = JSON.parse(JSON.stringify(validRecord));
  const pin = makeValidReceipt(bucket);

  const expPromise = openRemoteCipherExport(bucket, ctx, rec, pin, new AbortController().signal);
  ctx.instanceId = 'mutated';
  rec.job_id = '0'.repeat(32);
  pin.job_id = '0'.repeat(32);

  const exportRes = await expPromise;
  assert.equal(exportRes.receipt.job_id, validJobId);
  assert.equal(exportRes.receipt.context.instanceId, validContext.instanceId);
  const { sha256 } = await consumeStreamToHash(exportRes.body);
  assert.equal(sha256, validRecord.artifact.sha256);
});

await test('mutation of returned receipt does not compromise internal pinned verification', async () => {
  const bucket = createMockStorage();
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  exportRes.receipt.job_id = '0'.repeat(32);
  exportRes.receipt.object_version = 'tampered-version';
  exportRes.receipt.artifact.bytes = 1;
  const { bytesRead, sha256 } = await consumeStreamToHash(exportRes.body);
  assert.equal(bytesRead, validRecord.artifact.bytes);
  assert.equal(sha256, validRecord.artifact.sha256);
});

await test('large 14,627,035 byte owned image cipher verified and streamed properly', async () => {
  const largeCipher = new Uint8Array(14627035);
  for (let i = 0; i < 200000; i++) largeCipher[i] = (i * 7) % 256;
  largeCipher[largeCipher.length - 1] = 42;
  const largeSha = createHash('sha256').update(largeCipher).digest('hex');
  const largeRecord = {
    schema: 'sg.local-job.v1',
    job_id: validJobId,
    request_digest: validReqDigest,
    state: 'artifact-verified',
    artifact: {
      leaf: `sg-encrypted-${validJobId}.bin`,
      bytes: largeCipher.byteLength,
      sha256: largeSha,
    },
  };

  const slices = [];
  const hostChunkSize = 256 * 1024;
  for (let offset = 0; offset < largeCipher.byteLength; offset += hostChunkSize) {
    slices.push(largeCipher.subarray(offset, Math.min(offset + hostChunkSize, largeCipher.byteLength)));
  }

  const bucket = createMockStorage(validContext, largeRecord, largeCipher, {
    cipherChunkSlices: slices,
  });
  const pin = makeValidReceipt(bucket);
  pin.artifact = { ...largeRecord.artifact };

  const exportRes = await openRemoteCipherExport(bucket, validContext, largeRecord, pin, new AbortController().signal);
  const { bytesRead, sha256 } = await consumeStreamToHash(exportRes.body);
  assert.equal(bytesRead, 14627035);
  assert.equal(sha256, largeSha);
});

await test('invalid cipher get metadata cancels body and rejects export', async () => {
  let bodyCancelled = false;
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    overrideCipherMeta: { keyId: 'mismatched-key' },
    onCipherBodyCancel() { bodyCancelled = true; },
  });
  const pin = makeValidReceipt(bucket);

  await assert.rejects(
    openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal),
    /Remote cipher export held/
  );
});

await test('cipher size mismatch on get rejects export', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    cipherSize: 99999,
  });
  const pin = makeValidReceipt(bucket);
  await assert.rejects(
    openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal),
    /Remote cipher export held/
  );
});

await test('cipher get version drift rejects export', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher);
  const pin = makeValidReceipt(bucket);
  const origGet = bucket.get.bind(bucket);
  bucket.get = async (k) => {
    const res = await origGet(k);
    if (k === bucket.objectKey) {
      return { ...res, version: 'drifted-version' };
    }
    return res;
  };

  await assert.rejects(
    openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal),
    /Remote cipher export held/
  );
});

await test('short cipher body stream fails and holds', async () => {
  const shortCipher = testCipher.subarray(0, 50000);
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    customCipherGetStream: () => new ReadableStream({
      start(controller) {
        controller.enqueue(shortCipher);
        controller.close();
      }
    })
  });
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  await assert.rejects(
    consumeStreamToHash(exportRes.body),
    /Remote cipher export held/
  );
});

await test('overflow cipher body stream fails immediately before emitting extra bytes', async () => {
  const extraCipher = new Uint8Array(testCipher.byteLength + 10);
  extraCipher.set(testCipher);
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    customCipherGetStream: () => new ReadableStream({
      start(controller) {
        controller.enqueue(extraCipher);
        controller.close();
      }
    })
  });
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  await assert.rejects(
    consumeStreamToHash(exportRes.body),
    /Remote cipher export held/
  );
});

await test('final cipher version replacement during body stream reading causes final verification rejection', async () => {
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    onCipherHead: (count) => {
      if (count === 3) {
        const item = bucket.storage.get(bucket.objectKey);
        item.version = 'admin-replaced-ver';
      }
    }
  });
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  await assert.rejects(
    consumeStreamToHash(exportRes.body),
    /Remote cipher export held/
  );
});

await test('consumer cancels stream: underlying cipher reader is cancelled and cleaned up', async () => {
  let cipherBodyCancelled = false;
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    customCipherGetStream:()=>new ReadableStream({start(c){c.enqueue(testCipher);},cancel(){cipherBodyCancelled=true;}})
  });
  const pin = makeValidReceipt(bucket);
  const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
  const reader = exportRes.body.getReader();
  const first = await reader.read();
  assert.ok(!first.done);
  await reader.cancel('Consumer dropped stream');
  assert.equal(cipherBodyCancelled, true);
});

await test('unused stream budget expires and reader is cancelled without long sleep via fake clock', async () => {
  const originalNow = performance.now;
  const origSetTimeout = globalThis.setTimeout;
  let timeoutCb = null;
  globalThis.setTimeout = (cb, ms) => {
    if (ms === 30000) {
      if(timeoutCb===null)timeoutCb = cb;
      return 999;
    }
    return origSetTimeout(cb, ms);
  };

  let bodyCancelled = false;
  const bucket = createMockStorage(validContext, validRecord, testCipher, {
    customCipherGetStream:()=>new ReadableStream({start(c){c.enqueue(testCipher);},cancel(){bodyCancelled=true;}})
  });
  const pin = makeValidReceipt(bucket);

  try {
    const exportRes = await openRemoteCipherExport(bucket, validContext, validRecord, pin, new AbortController().signal);
    assert.ok(timeoutCb !== null);
    timeoutCb();
    const reader = exportRes.body.getReader();
    await assert.rejects(reader.read(), /Remote cipher export held/);
    assert.equal(bodyCancelled, true);
  } finally {
    globalThis.setTimeout = origSetTimeout;
    performance.now = originalNow;
  }
});

await test('late get result after abort is contained and body is canceled', async () => {
  const base = createMockStorage();
  const pin = makeValidReceipt(base);
  let startedResolve;
  const started = new Promise(r => startedResolve = r);
  let finish;
  let cipherCancelled = false;
  const ctrl = new AbortController();
  const bucket = {
    head: base.head.bind(base),
    get: (key) => {
      if (key === base.objectKey) {
        startedResolve();
        return new Promise(r => finish = r);
      }
      return base.get(key);
    }
  };

  const exportPromise = openRemoteCipherExport(bucket, validContext, validRecord, pin, ctrl.signal);
  const assertion = assert.rejects(exportPromise, /Remote cipher export held/);
  await started;
  ctrl.abort();
  await assertion;
  const obj = base.storage.get(base.objectKey);
  finish({ ...obj, body: new ReadableStream({ cancel() { cipherCancelled = true; } }) });
  await new Promise(r => setTimeout(r, 20));
  assert.equal(cipherCancelled, true);
});

await test('late get body getter fault does not escape boundary', async () => {
  const base = createMockStorage();
  const pin = makeValidReceipt(base);
  let startedResolve;
  const started = new Promise(r => startedResolve = r);
  let finish;
  const ctrl = new AbortController();
  const bucket = {
    head: base.head.bind(base),
    get: (key) => {
      if (key === base.objectKey) {
        startedResolve();
        return new Promise(r => finish = r);
      }
      return base.get(key);
    }
  };

  const exportPromise = openRemoteCipherExport(bucket, validContext, validRecord, pin, ctrl.signal);
  const assertion = assert.rejects(exportPromise, /Remote cipher export held/);
  await started;
  ctrl.abort();
  await assertion;
  finish({ get body() { throw new Error('OWNED DIAGNOSTIC GETTER FAULT'); } });
  await new Promise(r => setTimeout(r, 20));
});

await test('cleanup observer abort cannot produce false ACK', async () => {
  const bucket = createMockStorage();
  const pin = makeValidReceipt(bucket);
  const ctrl = new AbortController();
  const remove = ctrl.signal.removeEventListener.bind(ctrl.signal);
  ctrl.signal.removeEventListener = (...args) => {
    ctrl.abort();
    return remove(...args);
  };
  await assert.rejects(
    (async()=>{const exported=await openRemoteCipherExport(bucket,validContext,validRecord,pin,ctrl.signal);await consumeStreamToHash(exported.body);})(),
    /Remote cipher export held/
  );
});

await test('small host chunks preserve bounded backpressure',async()=>{let reads=0;let offset=0;const bucket=createMockStorage(validContext,validRecord,testCipher,{customCipherGetStream:()=>new ReadableStream({pull(c){reads++;if(offset===testCipher.length){c.close();return;}c.enqueue(testCipher.subarray(offset,offset+10000));offset+=10000;}},{highWaterMark:0})});const exported=await openRemoteCipherExport(bucket,validContext,validRecord,makeValidReceipt(bucket),new AbortController().signal);const reader=exported.body.getReader();try{await reader.read();assert.ok(reads<=2,'producer consumed '+reads+' host chunks for first consumer pull');}finally{await reader.cancel();reader.releaseLock();}});
await test('abort observed during final enqueue cannot produce clean EOF',async()=>{const bucket=createMockStorage();const ctrl=new AbortController();const exported=await openRemoteCipherExport(bucket,validContext,validRecord,makeValidReceipt(bucket),ctrl.signal);const original=ReadableStreamDefaultController.prototype.enqueue;ReadableStreamDefaultController.prototype.enqueue=function(v){const result=original.call(this,v);if(v instanceof Uint8Array&&v.length===65536)ctrl.abort();return result;};try{await assert.rejects(consumeStreamToHash(exported.body),/Remote cipher export held/);}finally{ReadableStreamDefaultController.prototype.enqueue=original;await exported.body.cancel().catch(()=>{});}});
for(const mode of ['missing-pin','wrong-context','extra-record','getter-fault'])await test(`input ${mode} holds before R2 effects`,async()=>{let calls=0;const bucket={head:async()=>{calls++;return null;},get:async()=>{calls++;return null;}};let ctx=validContext,rec=validRecord,pin=makeValidReceipt(createMockStorage());if(mode==='missing-pin')pin=undefined;if(mode==='wrong-context')ctx={...ctx,instanceId:'UPPER'};if(mode==='extra-record')rec={...rec,unexpected:true};if(mode==='getter-fault')ctx=Object.defineProperty({...ctx},'instanceId',{get(){throw Error('OWNED-DIAGNOSTIC');}});await assert.rejects(openRemoteCipherExport(bucket,ctx,rec,pin,new AbortController().signal),{message:'Remote cipher export held'});assert.equal(calls,0);});
