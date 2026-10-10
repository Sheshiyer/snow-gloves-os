import test from 'node:test';
import assert from 'node:assert/strict';
import {importCipherStream} from './recovery-io.ts';
// Node-only fixture. Production requires the Workers native FixedLengthStream.
class FixtureFixedLengthStream extends TransformStream {
 constructor(bytes){let seen=0;super({transform(chunk,controller){seen+=chunk.byteLength;if(seen>bytes) throw new Error('overflow');controller.enqueue(chunk);},flush(){if(seen!==bytes) throw new Error('truncated');}});}
}
async function fixture(fn){const previous=globalThis.FixedLengthStream;globalThis.FixedLengthStream=FixtureFixedLengthStream;try{return await fn();}finally{if(previous===undefined) delete globalThis.FixedLengthStream;else globalThis.FixedLengthStream=previous;}}
const source=bytes=>new ReadableStream({start(c){c.enqueue(Uint8Array.from(bytes));c.close();}});
const consume=async(body)=>{const bytes=await new Response(body).arrayBuffer();return bytes.byteLength;};
test('fixed import awaits both exact source EOF and receiver acknowledgment',()=>fixture(async()=>{assert.equal(await importCipherStream(source([1,2,3]),3,consume,new AbortController().signal),3);}));
test('truncation and overflow hold despite an early successful receiver acknowledgment',()=>fixture(async()=>{for(const bytes of [[1,2],[1,2,3,4]]) await assert.rejects(importCipherStream(source(bytes),3,async body=>{void new Response(body).arrayBuffer().catch(()=>{});return 'ack';},new AbortController().signal),/IMPORT_STREAM/);}));
test('late source verification failure holds after receiver has acknowledged',()=>fixture(async()=>{let index=0;const cipher=new ReadableStream({pull(c){if(index++===0)c.enqueue(new Uint8Array([1,2,3]));else c.error(new Error('version changed'));}});await assert.rejects(importCipherStream(cipher,3,async body=>{void new Response(body).arrayBuffer().catch(()=>{});return 'ack';},new AbortController().signal),/IMPORT_STREAM/);}));
test('client cancellation cancels source and exchange, never acknowledging import',()=>fixture(async()=>{let cancelled=false;const parent=new AbortController(),cipher=new ReadableStream({cancel(){cancelled=true;}});const work=importCipherStream(cipher,3,async(body,signal)=>{void new Response(body).arrayBuffer().catch(()=>{});return new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(new Error('cancelled')),{once:true}));},parent.signal);await new Promise(r=>setTimeout(r,0));parent.abort();await assert.rejects(work,/IMPORT_STREAM/);assert.equal(cancelled,true);}));
test('deadline holds an exchange that ignores cancellation and bounds uncertain cleanup',()=>fixture(async()=>{const began=Date.now();await assert.rejects(importCipherStream(source([1,2,3]),3,async()=>new Promise(()=>{}),new AbortController().signal,10),/IMPORT_STREAM_CLEANUP_HELD/);assert.ok(Date.now()-began<1500);}));
test('missing native fixed-length support holds instead of unknown-length fallback',async()=>{const saved=globalThis.FixedLengthStream;delete globalThis.FixedLengthStream;try{await assert.rejects(importCipherStream(source([1]),1,consume,new AbortController().signal),/FIXED_LENGTH_STREAM_UNAVAILABLE/);}finally{if(saved!==undefined)globalThis.FixedLengthStream=saved;}});
