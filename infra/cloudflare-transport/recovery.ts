import type { RemoteReceipt } from './remote-checkpoint.ts';

export const RECOVERY_BUDGET_MS = 120_000;
export const CHECKPOINT_INTERVAL_MS = 900_000;
export const EXPIRY_AGE_MS = 86_400_000;
export const RECOVERY_STORAGE_KEY = 'sg.gateway-recovery.v1';
export interface RuntimeContext { instanceId: string; imageDigest: string; keyId: string; runtimeVersion: '3.8.50' }
export interface RuntimeIdentity extends RuntimeContext { schema: 'sg.runtime-identity.v1'; generation: string }
export interface Checkpoint { receipt: RemoteReceipt; confirmedAt: number; held: boolean }
export interface Operation {
  kind: 'bootstrap' | 'recovery' | 'checkpoint' | 'adoption'; generation: string; jobId: string;
  phase: 'prepared' | 'launched' | 'imported' | 'restored' | 'exported' | 'confirmed';
  startedAt: number; attempts: number; nextAttemptAt: number;
  source: Checkpoint | null; receipt: RemoteReceipt | null;
}
export interface RecoveryState {
  schema: 'sg.gateway-recovery.v1'; context: RuntimeContext; bootstrapConsumed: boolean;
  generation: string | null; readyGeneration: string | null; operation: Operation | null;
  checkpoints: Checkpoint[]; status: 'stopped' | 'recovering' | 'ready' | 'held';
  failure: string | null; nextCheckpointAt: number | null;
}
export interface RecoveryStorage {
  get<T>(key: string): Promise<T | undefined>; put<T>(key: string, value: T): Promise<unknown>;
  sync(): Promise<unknown>; setAlarm(time: number): Promise<unknown>;
}
export interface RecoveryIO {
  running(): boolean;
  identity(signal: AbortSignal): Promise<RuntimeIdentity>;
  launch(generation: string, signal: AbortSignal): Promise<void>;
  ready(signal: AbortSignal): Promise<void>;
  restore(checkpoint: Checkpoint, restoreJob: string, signal: AbortSignal): Promise<void>;
  checkpoint(jobId: string, signal: AbortSignal): Promise<RemoteReceipt>;
  confirm(receipt: RemoteReceipt, signal: AbortSignal): Promise<void>;
  verify(receipt: RemoteReceipt, signal: AbortSignal): Promise<void>;
}
export class RecoveryHeld extends Error { readonly code: string; constructor(code: string) { super(code); this.code=code; } }
export class TransientRecoveryFailure extends Error {}
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonicalJson((value as Record<string, unknown>)[k])}`).join(',')}}`;
  return JSON.stringify(value);
}
export async function operationDigest(context: RuntimeContext, operation: string, request: object): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson({context, operation, request, schema: 'sg.operation-request.v1'}));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(b => b.toString(16).padStart(2, '0')).join('');
}
const hex32 = /^[0-9a-f]{32}$/;
const hex64 = /^[0-9a-f]{64}$/;
function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join() === [...keys].sort().join();
}
function contextValid(value: unknown): value is RuntimeContext {
  if (!exact(value, ['instanceId','imageDigest','keyId','runtimeVersion'])) return false;
  return typeof value.instanceId === 'string' && /^[a-z0-9-]{1,64}$/.test(value.instanceId) && typeof value.keyId === 'string' && /^[a-z0-9-]{1,64}$/.test(value.keyId) && value.runtimeVersion === '3.8.50' && typeof value.imageDigest === 'string' && hex64.test(value.imageDigest);
}
function timestamp(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) >= 0; }
function receiptValid(value: unknown, context: RuntimeContext): value is RemoteReceipt {
  if (!exact(value, ['schema','state','context','job_id','request_digest','artifact','object_key','object_version','commit_key','commit_version'])) return false;
  if (value.schema !== 'sg.remote-checkpoint.v1' || value.state !== 'remote-committed' || canonicalJson(value.context) !== canonicalJson(context) || typeof value.job_id !== 'string' || !hex32.test(value.job_id) || typeof value.request_digest !== 'string' || !hex64.test(value.request_digest)) return false;
  if (!exact(value.artifact, ['leaf','bytes','sha256']) || value.artifact.leaf !== `sg-encrypted-${value.job_id}.bin` || !Number.isSafeInteger(value.artifact.bytes) || (value.artifact.bytes as number) < 1 || (value.artifact.bytes as number) > 64*1024*1024+4136 || typeof value.artifact.sha256 !== 'string' || !hex64.test(value.artifact.sha256)) return false;
  const prefix = `cp/v1/${context.instanceId}/${context.imageDigest}/${value.job_id}/${value.request_digest}/${value.artifact.sha256}`;
  return value.object_key === `${prefix}.bin` && value.commit_key === `${prefix}.commit.json` && [value.object_version,value.commit_version].every(v => typeof v === 'string' && /^[\x21-\x7e]{1,256}$/.test(v));
}
function checkpointValid(value: unknown, context: RuntimeContext): value is Checkpoint {
  return exact(value,['receipt','confirmedAt','held']) && timestamp(value.confirmedAt) && typeof value.held === 'boolean' && receiptValid(value.receipt, context);
}
export function validateRecoveryState(value: unknown, context: RuntimeContext): RecoveryState {
  if (!exact(value,['schema','context','bootstrapConsumed','generation','readyGeneration','operation','checkpoints','status','failure','nextCheckpointAt']) || value.schema !== 'sg.gateway-recovery.v1' || !contextValid(value.context) || canonicalJson(value.context) !== canonicalJson(context) || typeof value.bootstrapConsumed !== 'boolean' || !['stopped','recovering','ready','held'].includes(String(value.status)) || !(value.failure === null || typeof value.failure === 'string' && /^[A-Z_]{1,80}$/.test(value.failure))) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  for (const k of ['generation','readyGeneration']) if (!(value[k] === null || typeof value[k] === 'string' && hex32.test(value[k] as string))) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  if (!(value.nextCheckpointAt === null || timestamp(value.nextCheckpointAt)) || !Array.isArray(value.checkpoints) || value.checkpoints.length > 256 || !value.checkpoints.every(c => checkpointValid(c,context))) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  if (new Set(value.checkpoints.map(c => c.receipt.job_id)).size !== value.checkpoints.length) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  const op = value.operation;
  if (op !== null && (!exact(op,['kind','generation','jobId','phase','startedAt','attempts','nextAttemptAt','source','receipt']) || !['bootstrap','recovery','checkpoint','adoption'].includes(String(op.kind)) || typeof op.generation !== 'string' || !hex32.test(op.generation) || op.generation !== value.generation || typeof op.jobId !== 'string' || !hex32.test(op.jobId) || !['prepared','launched','imported','restored','exported','confirmed'].includes(String(op.phase)) || !timestamp(op.startedAt) || !timestamp(op.nextAttemptAt) || !Number.isSafeInteger(op.attempts) || (op.attempts as number) < 0 || (op.attempts as number) > 3 || !(op.source === null || checkpointValid(op.source,context)) || !(op.receipt === null || receiptValid(op.receipt,context)))) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  if (value.generation===null && (value.readyGeneration!==null || op!==null)) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  if (op!==null) {
    const operation=op as unknown as Operation;
    if (operation.kind==='adoption') {
      if(!operation.source || operation.source.held || operation.receipt!==null || value.readyGeneration!==value.generation || !value.checkpoints.some(c=>canonicalJson(c)===canonicalJson(operation.source)) || !['prepared','launched','confirmed'].includes(operation.phase)) throw new RecoveryHeld('DURABLE_STATE_INVALID');
    } else if (operation.kind==='recovery') {
      if (!operation.source || operation.source.held || operation.receipt!==null || operation.jobId===operation.source.receipt.job_id || !value.checkpoints.some(c=>canonicalJson(c)===canonicalJson(operation.source)) || ['exported','confirmed'].includes(operation.phase)) throw new RecoveryHeld('DURABLE_STATE_INVALID');
    } else {
      if (operation.source!==null || ['imported','restored'].includes(operation.phase) || operation.receipt!==null && operation.receipt.job_id!==operation.jobId || ['exported','confirmed'].includes(operation.phase) && operation.receipt===null || operation.kind==='bootstrap' && !value.bootstrapConsumed || operation.kind==='checkpoint' && value.readyGeneration!==value.generation) throw new RecoveryHeld('DURABLE_STATE_INVALID');
    }
  }
  if (value.status === 'ready' && (value.readyGeneration !== value.generation || value.generation === null || value.checkpoints.length === 0)) throw new RecoveryHeld('DURABLE_STATE_INVALID');
  return structuredClone(value) as unknown as RecoveryState;
}

/** One DO owns one container. Durable progress is flushed and read back before every side effect. */
export class GatewayRecovery {
  private activeDeadline: number | null = null;
  private queue: Promise<unknown> = Promise.resolve();
  private recovery: Promise<void> | null = null;
  private storage: RecoveryStorage;
  private io: RecoveryIO;
  private context: RuntimeContext;
  private bootstrapOnce: boolean;
  private now: () => number;
  private sleep: (ms: number) => Promise<void>;
  private id: () => string;
  constructor(storage: RecoveryStorage, io: RecoveryIO, context: RuntimeContext,
    bootstrapOnce = false, now: () => number = Date.now,
    sleep: (ms: number) => Promise<void> = ms => new Promise(r => setTimeout(r,ms)),
    id: () => string = () => crypto.randomUUID().replaceAll('-','')) {
    this.storage=storage;this.io=io;this.context=context;this.bootstrapOnce=bootstrapOnce;this.now=now;this.sleep=sleep;this.id=id;
    if (!contextValid(context)) throw new RecoveryHeld('CONTEXT_INVALID');
  }
  private async bounded<T>(task: Promise<T>): Promise<T> {
    if(this.activeDeadline===null) return task;
    const remaining=this.activeDeadline-this.now();
    if(remaining<=0) {task.catch(()=>{});throw new RecoveryHeld('RECOVERY_DEADLINE');}
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {return await Promise.race([task,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new RecoveryHeld('RECOVERY_DEADLINE')),remaining);})]);}
    finally {if(timer) clearTimeout(timer);}
  }
  private serial<T>(fn: () => Promise<T>): Promise<T> { const task = this.queue.then(fn); this.queue = task.catch(() => {}); return task; }
  async state(): Promise<RecoveryState> {
    const stored = await this.bounded(this.storage.get(RECOVERY_STORAGE_KEY));
    if (stored !== undefined) return validateRecoveryState(stored,this.context);
    return {schema:'sg.gateway-recovery.v1',context:this.context,bootstrapConsumed:false,generation:null,readyGeneration:null,operation:null,checkpoints:[],status:'stopped',failure:null,nextCheckpointAt:null};
  }
  private async save(state: RecoveryState): Promise<void> {
    validateRecoveryState(state,this.context);
    await this.bounded(this.storage.put(RECOVERY_STORAGE_KEY,state)); await this.bounded(this.storage.sync());
    const read = await this.bounded(this.storage.get(RECOVERY_STORAGE_KEY));
    if (canonicalJson(read) !== canonicalJson(state)) throw new RecoveryHeld('DURABLE_READBACK_MISMATCH');
  }
  private latest(state: RecoveryState): Checkpoint | null { return state.checkpoints.reduce<Checkpoint|null>((a,b) => !b.held && (!a || b.confirmedAt >= a.confirmedAt) ? b : a,null); }
  /** Client abort only detaches this wait; it never aborts the shared recovery. */
  ensureReady(signal?: AbortSignal): Promise<void> {
    if (!this.recovery) this.recovery = this.serial(() => this.recover()).finally(() => {this.recovery = null;this.activeDeadline=null;});
    const shared = this.recovery;
    if (!signal) return shared;
    return new Promise((resolve,reject) => {
      const abort = () => { signal.removeEventListener('abort',abort); reject(new RecoveryHeld('CLIENT_CANCELLED')); };
      signal.addEventListener('abort',abort,{once:true});
      if (signal.aborted) abort();
      shared.then(() => { signal.removeEventListener('abort',abort); if (!signal.aborted) resolve(); }, error => {signal.removeEventListener('abort',abort); reject(error);});
    });
  }
  private async owned(state: RecoveryState, signal: AbortSignal): Promise<void> {
    const identity = await this.bounded(this.io.identity(signal));
    const expected = {schema:'sg.runtime-identity.v1',...this.context,generation:state.generation};
    if (canonicalJson(identity) !== canonicalJson(expected)) throw new RecoveryHeld('RUNTIME_IDENTITY_MISMATCH');
  }
  private async recover(): Promise<void> {
    this.activeDeadline=this.now()+RECOVERY_BUDGET_MS;
    let state = await this.state();
    if (state.status === 'held') throw new RecoveryHeld(state.failure ?? 'RECOVERY_HELD');
    const controller = new AbortController();
    const wasRunning=this.io.running();
    // A prepared recovery without a previously ready disk is still the same launch attempt.
    // Its identity, budget and retry spacing survive eviction. The same prepared bootstrap
    // intent may retry its launch; an owned/launched bootstrap whose unconfirmed disk
    // disappears cannot consume another gate or allocate a fresh empty generation.
    const pending=state.operation;
    const resumePrepared=!wasRunning && state.readyGeneration===null && pending?.phase==='prepared' &&
      (pending.kind==='recovery' || pending.kind==='bootstrap' && state.checkpoints.length===0);
    // A legitimately new disk starts a new generation; a running/prepared replay retains its budget.
    const deadline = (wasRunning || resumePrepared ? state.operation?.startedAt ?? this.now() : this.now())+RECOVERY_BUDGET_MS;
    this.activeDeadline=deadline;
    const timer = setTimeout(() => controller.abort(),RECOVERY_BUDGET_MS);
    try {
      if (wasRunning) {
        if (!state.generation) throw new RecoveryHeld('RUNNING_CONTAINER_UNOWNED');
        if (state.readyGeneration === state.generation && !state.operation) {
          const latest=this.latest(state);if(!latest) throw new RecoveryHeld('CONFIRMED_CHECKPOINT_MISSING');
          state.operation={kind:'adoption',generation:state.generation,jobId:this.id(),phase:'prepared',startedAt:this.now(),attempts:0,nextAttemptAt:this.now(),source:latest,receipt:null};
          state.status='recovering';state.failure=null;await this.save(state);
        }
      } else if(!resumePrepared) {
        const latest = this.latest(state);
        // A consumed gate cannot authorize another empty disk, even after an interrupted bootstrap.
        if (!latest && (state.checkpoints.length!==0 || !this.bootstrapOnce || state.bootstrapConsumed)) throw new RecoveryHeld('CONFIRMED_CHECKPOINT_MISSING');
        if(latest) await this.bounded(this.io.verify(latest.receipt,controller.signal));
        const generation = this.id();
        state.generation=generation; state.readyGeneration=null;
        state.operation={kind:latest ? 'recovery':'bootstrap',generation,jobId:this.id(),phase:'prepared',startedAt:this.now(),attempts:0,nextAttemptAt:this.now(),source:latest,receipt:null};
        if (!latest) state.bootstrapConsumed=true;
        state.status='recovering'; state.failure=null; await this.save(state);

      }
      if(resumePrepared && state.operation?.source) await this.bounded(this.io.verify(state.operation.source.receipt,controller.signal));
      const op = state.operation;
      if (!op) throw new RecoveryHeld('OPERATION_MISSING');
      while (true) {
        if (controller.signal.aborted || this.now() >= deadline || op.attempts >= 3) throw new RecoveryHeld('RECOVERY_RETRY_EXHAUSTED');
        if (op.nextAttemptAt > this.now()) { const delay=op.nextAttemptAt-this.now(); if (this.now()+delay >= deadline) throw new RecoveryHeld('RECOVERY_DEADLINE'); await this.bounded(this.sleep(delay)); }
        op.attempts++; await this.save(state);
        try {
          if(!this.io.running()) await this.bounded(this.io.launch(op.generation,controller.signal));
          await this.owned(state,controller.signal);
          if(op.phase==='prepared') {op.phase='launched';await this.save(state);}
          if (op.kind === 'recovery') {
            if (!op.source) throw new RecoveryHeld('RECOVERY_SOURCE_MISSING');
            await this.bounded(this.io.verify(op.source.receipt,controller.signal));
            await this.bounded(this.io.restore(op.source,op.jobId,controller.signal));
            op.phase='restored'; await this.save(state);
          } else if(op.kind==='adoption') {
            if(!op.source) throw new RecoveryHeld('ADOPTION_SOURCE_MISSING');
            await this.bounded(this.io.verify(op.source.receipt,controller.signal));
          } else await this.makeCheckpoint(state,controller.signal);
          await this.bounded(this.io.ready(controller.signal));
          if(op.kind==='adoption') {op.phase='confirmed';await this.save(state);}
          if (controller.signal.aborted || this.now() >= deadline) throw new RecoveryHeld('RECOVERY_DEADLINE');
          await this.admit(state,op.kind==='adoption' && state.nextCheckpointAt!==null ? state.nextCheckpointAt : this.now()+CHECKPOINT_INTERVAL_MS); return;
        } catch (error) {
          if (!(error instanceof TransientRecoveryFailure)) throw error;
          op.nextAttemptAt=this.now()+60_000; await this.save(state);
        }
      }
    } catch (error) {
      state.status='held'; state.failure=error instanceof RecoveryHeld ? error.code : 'RECOVERY_VERIFICATION_HELD';
      this.activeDeadline=this.now()+5000; await this.save(state); throw new RecoveryHeld(state.failure);
    } finally { clearTimeout(timer); controller.abort(); this.activeDeadline=null; }
  }
  private async admit(state: RecoveryState, nextCheckpointAt=this.now()+CHECKPOINT_INTERVAL_MS): Promise<void> {
    // Keep the completed intent durable until scheduling also succeeds. Scheduling failures
    // can then be repaired using the same restore/checkpoint identity rather than an empty slot.
    state.nextCheckpointAt=nextCheckpointAt;
    await this.save(state);
    await this.bounded(this.storage.setAlarm(state.nextCheckpointAt));
    const operation=state.operation;
    state.readyGeneration=state.generation;state.status='ready';state.operation=null;state.failure=null;
    try {await this.save(state);}
    catch(error) {state.operation=operation;state.status='recovering';throw error;}
  }
  private async makeCheckpoint(state: RecoveryState, signal: AbortSignal): Promise<void> {
    const op=state.operation!;
    if(state.checkpoints.length>=256 && !state.checkpoints.some(c=>c.receipt.job_id===op.jobId)) throw new RecoveryHeld('CHECKPOINT_LEDGER_FULL');
    if (!op.receipt) {
      const receipt=await this.bounded(this.io.checkpoint(op.jobId,signal));
      if(!receiptValid(receipt,this.context) || receipt.job_id!==op.jobId) throw new RecoveryHeld('CHECKPOINT_RECEIPT_INVALID');
      op.receipt=receipt; op.phase='exported'; await this.save(state);
    }
    await this.bounded(this.io.confirm(op.receipt,signal));
    op.phase='confirmed'; await this.save(state);
    if (!state.checkpoints.some(c=>c.receipt.job_id===op.receipt!.job_id)) state.checkpoints.push({receipt:op.receipt,confirmedAt:this.now(),held:false});
    await this.save(state);
  }
  alarm(): Promise<void> { return this.serial(async()=> {
    const state=await this.state();
    if (!this.io.running()) {
      // A stopped runtime does not repair a verification failure or clear its durable intent.
      if(state.status!=='held') {state.status='stopped';await this.save(state);}
      return;
    }
    if (state.status !== 'ready' || state.operation) return;
    this.activeDeadline=this.now()+RECOVERY_BUDGET_MS;
    const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),RECOVERY_BUDGET_MS);
    try {
      const latest=this.latest(state);if(!latest) throw new RecoveryHeld('CONFIRMED_CHECKPOINT_MISSING');
      // Persist the known-ready generation's verification intent before probing ownership.
      // A transient probe failure then remains repairable without granting unverified ownership.
      state.operation={kind:'adoption',generation:state.generation!,jobId:this.id(),phase:'prepared',startedAt:this.now(),attempts:1,nextAttemptAt:this.now(),source:latest,receipt:null};
      await this.save(state);
      await this.owned(state,controller.signal);
      state.operation.phase='launched';await this.save(state);
      if (state.nextCheckpointAt !== null && this.now()<state.nextCheckpointAt) {
        await this.admit(state,state.nextCheckpointAt);return;
      }
      state.operation={kind:'checkpoint',generation:state.generation!,jobId:state.operation.jobId,phase:'prepared',startedAt:state.operation.startedAt,attempts:1,nextAttemptAt:this.now(),source:null,receipt:null};
      await this.save(state); await this.makeCheckpoint(state,controller.signal);
      if (controller.signal.aborted) throw new RecoveryHeld('CHECKPOINT_DEADLINE');
      await this.admit(state);
    } catch {this.activeDeadline=this.now()+5000;state.status='held'; state.failure='CHECKPOINT_HELD'; await this.save(state); throw new RecoveryHeld('CHECKPOINT_HELD');}
    finally {clearTimeout(timer); controller.abort(); this.activeDeadline=null;}
  }); }
  /** Reviewed candidates only: R2 binding has no version-conditional delete. No deletion is attempted. */
  pruneCandidates(): Promise<Checkpoint[]> { return this.serial(async()=> {
    const state=await this.state(),latest=this.latest(state);
    const candidates=state.checkpoints.filter(c=>c!==latest && !c.held && c.receipt.job_id!==state.operation?.jobId && c.receipt.job_id!==state.operation?.source?.receipt.job_id && c.receipt.job_id!==state.operation?.receipt?.job_id && this.now()-c.confirmedAt>=EXPIRY_AGE_MS);
    this.activeDeadline=this.now()+RECOVERY_BUDGET_MS;
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),RECOVERY_BUDGET_MS);
    try {
      for(const candidate of candidates) {
        try {await this.bounded(this.io.verify(candidate.receipt,controller.signal));}
        catch {candidate.held=true;this.activeDeadline=this.now()+5000;await this.save(state);throw new RecoveryHeld('PRUNE_REVIEW_HELD');}
      }
      return candidates.map(c=>structuredClone(c));
    } finally {clearTimeout(timer);controller.abort();this.activeDeadline=null;}
  }); }
  /** Operator repair is internal; preserve the same disk generation and operation identity. */
  resumeHeld(): Promise<void> { return this.serial(async()=> {const state=await this.state(); if (state.status!=='held' || !state.operation) throw new RecoveryHeld('NO_HELD_OPERATION'); state.status='recovering';state.failure=null;state.operation.startedAt=this.now();state.operation.attempts=0;state.operation.nextAttemptAt=this.now();await this.save(state);}); }
}
