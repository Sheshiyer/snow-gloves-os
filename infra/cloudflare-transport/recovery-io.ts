import { validateEnv, readLimitedBody, CONTAINER_PORT, type LifecycleEnv } from './lifecycle.ts';
import { commitExportCipherToRemote } from './export-remote.ts';
import { confirmRemoteCheckpoint } from './durable-receipt.ts';
import { verifyRemoteReceipt } from './verify-remote-receipt.ts';
import { openRemoteCipherExport } from './remote-cipher-export.ts';
import type { RemoteReceipt } from './remote-checkpoint.ts';
import { canonicalJson, operationDigest, RecoveryHeld, TransientRecoveryFailure, type RuntimeContext, type RuntimeIdentity, type RecoveryIO } from './recovery.ts';

class RuntimeInitializing extends Error {}

export function runtimeContext(container: Container, env: LifecycleEnv): RuntimeContext {
  validateEnv(env);
  const image=container.images?.base;
  if (typeof image !== 'string' || !/^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:\/[a-z0-9]+(?:[._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$/.test(image)) throw new RecoveryHeld('IMAGE_PIN_INVALID');
  return {instanceId:env.GATEWAY_INSTANCE_ID,imageDigest:image.slice(-64),keyId:env.SG_BACKUP_KEY_ID,runtimeVersion:'3.8.50'};
}
export function localRecord(receipt: RemoteReceipt) {
  return {schema:'sg.local-job.v1',job_id:receipt.job_id,request_digest:receipt.request_digest,state:'artifact-verified',artifact:receipt.artifact};
}
/** Workers derives Content-Length from this native stream, not a caller-supplied header.
 * Success requires the verified source to reach EOF and the receiver to acknowledge it.
 */
export async function importCipherStream<T>(source: ReadableStream<Uint8Array>, bytes: number,
  exchange: (body: ReadableStream<Uint8Array>, signal: AbortSignal) => Promise<T>,
  signal: AbortSignal, timeoutMs = 25_000): Promise<T> {
  if(!Number.isSafeInteger(bytes) || bytes<1 || bytes>64*1024*1024+4136 || !Number.isInteger(timeoutMs) || timeoutMs<1 || timeoutMs>25_000) throw new RecoveryHeld('IMPORT_STREAM_INVALID');
  if(typeof FixedLengthStream!=='function') {
    // Native support is mandatory in production. Node fixtures install their own explicit test seam.
    void source.cancel().catch(()=>{});throw new RecoveryHeld('FIXED_LENGTH_STREAM_UNAVAILABLE');
  }
  const controller=new AbortController();
  const abort=()=>controller.abort();signal.addEventListener('abort',abort,{once:true});
  const timer=setTimeout(abort,timeoutMs);
  if(signal.aborted) abort();
  let pipe: Promise<void> | null=null;
  let response: Promise<T> | null=null;
  let stoppedListener: (()=>void) | undefined;
  let succeeded=false;
  try {
    if(controller.signal.aborted) throw new RecoveryHeld('IMPORT_STREAM_CANCELLED');
    const fixed=new FixedLengthStream(bytes);
    pipe=source.pipeTo(fixed.writable,{signal:controller.signal}).catch(()=>{controller.abort();throw new RecoveryHeld('IMPORT_STREAM_HELD');});
    response=Promise.resolve().then(()=>exchange(fixed.readable,controller.signal)).catch(error=>{controller.abort();throw error;});
    const stopped=new Promise<never>((_,reject)=>{
      stoppedListener=()=>reject(new RecoveryHeld('IMPORT_STREAM_CANCELLED'));
      controller.signal.addEventListener('abort',stoppedListener,{once:true});
      if(controller.signal.aborted) stoppedListener();
    });
    const [,ack]=await Promise.race([Promise.all([pipe,response]),stopped]);
    if(controller.signal.aborted) throw new RecoveryHeld('IMPORT_STREAM_CANCELLED');
    succeeded=true;
    return ack;
  } finally {
    clearTimeout(timer);signal.removeEventListener('abort',abort);
    if(stoppedListener) controller.signal.removeEventListener('abort',stoppedListener);
    if(!succeeded) {
      controller.abort();
      if(!pipe) void source.cancel().catch(()=>{});
      let cleanupTimer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          Promise.allSettled([...(pipe?[pipe]:[]),...(response?[response]:[])]),
          new Promise<never>((_,reject)=>{cleanupTimer=setTimeout(()=>reject(new RecoveryHeld('IMPORT_STREAM_CLEANUP_HELD')),1000);}),
        ]);
      } finally {if(cleanupTimer) clearTimeout(cleanupTimer);}
    }
  }
}

/** All calls remain container-internal; no management route is added to the public Worker. */
export function createRecoveryIO(storage: Pick<DurableObjectStorage,'transaction'|'get'|'sync'>, bucket: R2Bucket,
  container: Container, env: LifecycleEnv): RecoveryIO {
  const context=runtimeContext(container,env);
  const port=container.getTcpPort(CONTAINER_PORT);
  async function management(path: string, init: RequestInit, signal: AbortSignal): Promise<unknown> {
    const controller=new AbortController();
    const abort=()=>controller.abort();signal.addEventListener('abort',abort,{once:true}); if(signal.aborted) abort();
    const timer=setTimeout(abort,25_000);
    try {
      const request=Promise.resolve().then(()=>port.fetch(`http://runtime.internal:8080/_management/${path}`,{...init,headers:{Authorization:`Bearer ${env.MANAGEMENT_KEY}`,...init.headers},signal:controller.signal,redirect:'manual'})).then(response=>{
        if(controller.signal.aborted) {void response.body?.cancel().catch(()=>{});throw new RecoveryHeld('MANAGEMENT_DEADLINE');}
        return response;
      }).catch(error=>{
        if(controller.signal.aborted) throw new RecoveryHeld('MANAGEMENT_DEADLINE');
        if(error instanceof RecoveryHeld) throw error;
        if(error instanceof TypeError) throw new TransientRecoveryFailure('Management network unavailable');
        throw new RecoveryHeld('MANAGEMENT_TRANSPORT_HELD');
      });
      const stopped=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new RecoveryHeld('MANAGEMENT_DEADLINE')),{once:true}));
      if(controller.signal.aborted) throw new RecoveryHeld('MANAGEMENT_DEADLINE');
      const response=await Promise.race([request,stopped]);
      const bytes=await readLimitedBody(response.body,8192,25_000,controller.signal);
      if(response.status!==200) {
        // Restore 503 includes decryption/verification failures: never infer transient from it.
        if(path==='ready' && response.status===503) throw new RuntimeInitializing();
        if(path!=='restore' && path!=='import' && [502,504].includes(response.status)) throw new TransientRecoveryFailure('Management transport unavailable');
        throw new RecoveryHeld([401,403].includes(response.status) ? 'MANAGEMENT_AUTH_HELD':'MANAGEMENT_RESPONSE_HELD');
      }
      if(!/^application\/json(?:;|$)/i.test(response.headers.get('content-type')??'')) throw new RecoveryHeld('MANAGEMENT_RESPONSE_INVALID');
      try {return JSON.parse(new TextDecoder('utf-8',{fatal:true,ignoreBOM:false}).decode(bytes));} catch {throw new RecoveryHeld('MANAGEMENT_RESPONSE_INVALID');}
    } finally {clearTimeout(timer);signal.removeEventListener('abort',abort);controller.abort();}
  }
  const json=(value: object):RequestInit=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  return {
    running:()=>container.running,
    identity:async signal=> {
      let timer: ReturnType<typeof setTimeout> | undefined;
      let abort: (() => void) | undefined;
      try {
        const inspect=await Promise.race([container.inspect(),new Promise<never>((_,reject)=>{
          abort=()=>reject(new RecoveryHeld('INSPECT_TIMEOUT'));
          timer=setTimeout(abort,25_000);signal.addEventListener('abort',abort,{once:true});
          if(signal.aborted) abort();
        })]);
        if(!inspect || inspect.image!==container.images.base) throw new RecoveryHeld('CONTAINER_IMAGE_MISMATCH');
      } finally {if(timer) clearTimeout(timer);if(abort) signal.removeEventListener('abort',abort);}
      return await management('identity',{method:'GET'},signal) as RuntimeIdentity;
    },
    launch:async(generation,signal)=> {
      if(container.running || !/^[0-9a-f]{32}$/.test(generation)) throw new RecoveryHeld('LAUNCH_OWNERSHIP_HELD');
      const {envToInject}=validateEnv({...env,GATEWAY_INITIALIZE_FRESH:'1'});
      envToInject.SG_IMAGE_DIGEST=context.imageDigest;envToInject.SG_RUNTIME_GENERATION=generation;
      await container.start({image:container.images.base,env:envToInject,enableInternet:false,instance:'standard-1'});
      const deadline=Date.now()+90_000;
      while(!signal.aborted && Date.now()<deadline) {
        try {const ready=await management('ready',{method:'GET'},signal);if(canonicalJson(ready)==='{"ready":true}') return;} catch(error) {if(signal.aborted) break;if(!(error instanceof RuntimeInitializing)) throw error;}
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      throw new RecoveryHeld('INITIALIZATION_DEADLINE');
    },
    ready:async signal=> {if(canonicalJson(await management('ready',{method:'GET'},signal))!=='{"ready":true}') throw new RecoveryHeld('RUNTIME_NOT_READY');},
    checkpoint:async(jobId,signal)=> {
      const payload={job_id:jobId,request_digest:await operationDigest(context,'checkpoint',{job_id:jobId})};
      const result=await management('checkpoint',json(payload),signal) as Record<string,unknown>;
      if(result.schema!=='sg.local-job.v1' || result.job_id!==jobId || result.request_digest!==payload.request_digest || result.state!=='artifact-verified') throw new RecoveryHeld('CHECKPOINT_RESPONSE_INVALID');
      return commitExportCipherToRemote(bucket,port,context,payload,env.MANAGEMENT_KEY,signal);
    },
    confirm:async(receipt,signal)=> {await confirmRemoteCheckpoint(storage,bucket,context,localRecord(receipt),signal,receipt);},
    verify:async(receipt,signal)=> {
      const raw=await storage.get<string>('sg.durable-confirmations.v1');
      let registry: {schema?:string;jobs?:Array<{state?:string;context?:unknown;record?:unknown;receipt?:unknown}>};
      try {if(typeof raw!=='string' || raw.length>1024*1024) throw new Error(); registry=JSON.parse(raw);} catch {throw new RecoveryHeld('DURABLE_CONFIRMATION_MISSING');}
      if(registry.schema!=='sg.durable-registry.v1' || !Array.isArray(registry.jobs) || registry.jobs.length>256 || !registry.jobs.some(job=>job.state==='confirmed' && canonicalJson(job.context)===canonicalJson(context) && canonicalJson(job.record)===canonicalJson(localRecord(receipt)) && canonicalJson(job.receipt)===canonicalJson(receipt))) throw new RecoveryHeld('DURABLE_CONFIRMATION_MISSING');
      await verifyRemoteReceipt(bucket,context,localRecord(receipt),signal,receipt);
    },
    restore:async(checkpoint,restoreJob,signal)=> {
      const receipt=checkpoint.receipt,record=localRecord(receipt);
      const exported=await openRemoteCipherExport(bucket,context,record,receipt,signal);
      const metadata=canonicalJson({context,record,remote_receipt:receipt});
      if(metadata.length>8192) throw new RecoveryHeld('IMPORT_METADATA_OVERSIZED');
      const imported=await importCipherStream(exported.body,receipt.artifact.bytes,(body,importSignal)=>management('import',{method:'POST',headers:{'Content-Type':'application/vnd.sg.cipher-export+v1','X-SG-Import-Metadata':metadata},body},importSignal),signal);
      const importedRecord=imported as Record<string,unknown>;
      const expectedImport={schema:'sg.local-cipher-import.v1',state:'cipher-journal-bound',context,job_id:receipt.job_id,request_digest:receipt.request_digest,artifact:receipt.artifact,replay_stage:importedRecord?.replay_stage,replay_journal:importedRecord?.replay_journal};
      if(typeof importedRecord?.replay_stage!=='boolean' || typeof importedRecord?.replay_journal!=='boolean' || canonicalJson(imported)!==canonicalJson(expectedImport)) throw new RecoveryHeld('IMPORT_RESPONSE_INVALID');
      const request={restore_job_id:restoreJob,source_checkpoint_job_id:receipt.job_id,source_request_digest:receipt.request_digest,...receipt.artifact};
      const payload={...request,request_digest:await operationDigest(context,'restore',request)};
      const result=await management('restore',json(payload),signal);
      if(canonicalJson(result)!==canonicalJson({schema:'sg.restore-intent.v1',state:'completed-local',payload}) && canonicalJson(result)!==canonicalJson({schema:'sg.restore-intent.v1',state:'completed-local',payload,historical:true})) throw new RecoveryHeld('RESTORE_RESPONSE_INVALID');
    },
  };
}
