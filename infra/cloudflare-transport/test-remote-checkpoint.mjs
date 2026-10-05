import test from 'node:test';
import assert from 'node:assert/strict';
import {commitRemoteCheckpoint} from './remote-checkpoint.ts';
import {createHash} from 'node:crypto';
const context={instanceId:'owned-instance',runtimeVersion:'3.8.50',imageDigest:'c'.repeat(64),keyId:'owned-key'};const job='a'.repeat(32);const canonical=JSON.stringify({context:{imageDigest:context.imageDigest,instanceId:context.instanceId,keyId:context.keyId,runtimeVersion:context.runtimeVersion},operation:'checkpoint',request:{job_id:job},schema:'sg.operation-request.v1'});const digest=createHash('sha256').update(canonical).digest('hex');const body=new TextEncoder().encode('owned cipher');const hash=createHash('sha256').update(body).digest('hex');const record={schema:'sg.local-job.v1',job_id:job,request_digest:digest,state:'artifact-verified',artifact:{leaf:'sg-encrypted-'+job+'.bin',bytes:body.length,sha256:hash}};const key=`cp/v1/${context.instanceId}/${context.imageDigest}/${job}/${digest}/${hash}.bin`;const metadata={instanceId:context.instanceId,runtimeVersion:context.runtimeVersion,imageDigest:context.imageDigest,keyId:context.keyId,job_id:job,request_digest:digest,bytes:String(body.length),sha256:hash};const object={key,version:'object-v1',size:body.length,checksums:{sha256:Uint8Array.from(Buffer.from(hash,'hex')).buffer},customMetadata:metadata};
await test('actual journal identity and replay cancellation',async()=>{
const results={};
let calls=0;const blocked={head:async()=>{calls++;throw Error('owned controlled downstream stop');},get:async()=>null,put:async()=>null};try{await commitRemoteCheckpoint(blocked,context,record,new ReadableStream(),new AbortController().signal);}catch{}results.valid_actual_journal_reaches_binding=calls===1;
const {schema,...missing}=record;calls=0;try{await commitRemoteCheckpoint(blocked,context,missing,new ReadableStream(),new AbortController().signal);}catch{}results.missing_schema_denied_before_binding=calls===0;
let release;const pendingCancel=new Promise(r=>release=r);const ctrl=new AbortController();const hangingSource=new ReadableStream({cancel(){return pendingCancel;}});const replayBucket={head:async()=>object,get:async()=>null,put:async()=>null};let settled=false;const p=commitRemoteCheckpoint(replayBucket,context,record,hangingSource,ctrl.signal).then(()=>{settled=true;},()=>{settled=true;});await new Promise(r=>setTimeout(r,20));ctrl.abort();await new Promise(r=>setTimeout(r,40));results.abort_while_replay_cancel_pending_returns_bounded=settled;release();await p;

for(const [key,value] of Object.entries(results)){if(typeof value==="boolean")assert.equal(value,true,key);}
});
await test('strict metadata and commit key',async()=>{
const results={};
async function observeInvalidHead(obj){let calls=0;const bucket={head:async()=>obj,get:async()=>{calls++;throw Error('owned controlled stop');},put:async()=>null};try{await commitRemoteCheckpoint(bucket,context,record,new ReadableStream(),new AbortController().signal);}catch{}return calls===0;}
results.extra_object_metadata_denied=await observeInvalidHead({...object,customMetadata:{...metadata,unexpected:'untrusted'}});
results.nonascii_object_version_denied=await observeInvalidHead({...object,version:'invalid\nversion'});
let commit=null,seenGet=0;const bucket={head:async()=>object,get:async()=>{seenGet++;return commit;},put:async(k,bytes,opts)=>{const arr=new Uint8Array(bytes);const checksum=await crypto.subtle.digest('SHA-256',arr);commit={key:'wrong-key',version:'commit-version',size:arr.byteLength,checksums:{sha256:checksum},customMetadata:opts.customMetadata,body:new ReadableStream({start(c){c.enqueue(arr);c.close();}})};return commit;}};let accepted=false;try{await commitRemoteCheckpoint(bucket,context,record,new ReadableStream(),new AbortController().signal);accepted=true;}catch{}results.wrong_commit_object_key_denied=!accepted;

for(const [key,value] of Object.entries(results)){if(typeof value==="boolean")assert.equal(value,true,key);}
});
await test('fragmented commit body bounds abort listeners',async()=>{
const results={};
const active=new WeakMap();let peak=0;const add=AbortSignal.prototype.addEventListener;const remove=AbortSignal.prototype.removeEventListener;
const {setMaxListeners}=await import('node:events');
AbortSignal.prototype.addEventListener=function(type,listener,options){if(type==='abort'){setMaxListeners(0,this);const count=(active.get(this)||0)+1;active.set(this,count);peak=Math.max(peak,count);}return add.call(this,type,listener,options);};
AbortSignal.prototype.removeEventListener=function(type,listener,options){if(type==='abort')active.set(this,Math.max(0,(active.get(this)||0)-1));return remove.call(this,type,listener,options);};
let commit=null;const bucket={head:async()=>object,get:async()=>commit,put:async(k,bytes,opts)=>{const arr=new Uint8Array(bytes);const checksum=await crypto.subtle.digest('SHA-256',arr);let index=0;commit={key:k,version:'commit-version',size:arr.length,checksums:{sha256:checksum},customMetadata:opts.customMetadata,body:new ReadableStream({pull(c){if(index<arr.length)c.enqueue(arr.slice(index,index+++1));else c.close();}})};return commit;}};
try{const receipt=await commitRemoteCheckpoint(bucket,context,record,new ReadableStream(),new AbortController().signal);results.positive_state=receipt.state==='remote-committed';results.abort_listener_count_bounded=peak<=4;results.peak_abort_listeners=peak;}finally{AbortSignal.prototype.addEventListener=add;AbortSignal.prototype.removeEventListener=remove;}

for(const [key,value] of Object.entries(results)){if(typeof value==="boolean")assert.equal(value,true,key);}
});
await test('late commit outcome and stalled digest cancellation',async()=>{
const results={};
let startedResolve;const started=new Promise(r=>startedResolve=r);let finishPut;let stored=false;let getCalls=0;const bucket={head:async()=>object,get:async()=>{getCalls++;return null;},put:async()=>{startedResolve();return new Promise(r=>finishPut=r);}};const ctrl=new AbortController();let succeeded=false;let settled=false;const promise=commitRemoteCheckpoint(bucket,context,record,new ReadableStream(),ctrl.signal).then(()=>{succeeded=true;settled=true;},()=>{settled=true;});await started;ctrl.abort();await new Promise(r=>setTimeout(r,20));results.pending_commit_abort_returns_bounded=settled&&!succeeded;stored=true;finishPut({key:'late-commit',version:'late-version'});await promise;await new Promise(r=>setTimeout(r,20));results.late_commit_exists_but_not_acknowledged=stored&&!succeeded;results.no_new_get_after_terminal=getCalls===1;
const original=crypto.subtle.digest;let digestStarted;const digestGate=new Promise(r=>digestStarted=r);crypto.subtle.digest=async()=>{digestStarted();return new Promise(()=>{});};const secondCtrl=new AbortController();let calls=0;let secondSettled=false;const blocked={head:async()=>{calls++;return object;},get:async()=>null,put:async()=>null};try{const p=commitRemoteCheckpoint(blocked,context,record,new ReadableStream(),secondCtrl.signal).then(()=>secondSettled=true,()=>secondSettled=true);await digestGate;secondCtrl.abort();await new Promise(r=>setTimeout(r,20));results.abort_stalled_digest_bounded_before_effects=secondSettled&&calls===0;await p;}finally{crypto.subtle.digest=original;}

for(const [key,value] of Object.entries(results)){if(typeof value==="boolean")assert.equal(value,true,key);}
});
await test('absolute deadline after observers',async()=>{
const results={};let now=0;let calls=0;const original=performance.now;performance.now=()=>now;const bucket={head:async()=>object,get:async()=>{calls++;throw Error('owned controlled stop');},put:async()=>null};try{const source=new ReadableStream({cancel(){now=30001;}});try{await commitRemoteCheckpoint(bucket,context,record,source,new AbortController().signal);}catch{}results.absolute_deadline_after_observer_prevents_new_binding=calls===0;}finally{performance.now=original;}
for(const [key,value] of Object.entries(results)){if(typeof value==="boolean")assert.equal(value,true,key);}
});
