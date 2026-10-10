import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from './node_modules/esbuild/lib/main.js';
import {Miniflare,convertV4MiniflareOptions} from './node_modules/miniflare/dist/src/index.js';

// A real local workerd fetch reaches an owned HTTP receiver; no Node stream polyfill is used here.
test('native workerd sends exact Content-Length and holds truncated or overflow imports', {timeout:20000},async()=>{
 const observations=[];
 const server=createServer((request,response)=>{
  const chunks=[];let count=0;
  const item={length:request.headers['content-length'],transfer:request.headers['transfer-encoding']??null,count:0,aborted:false};observations.push(item);
  request.on('data',chunk=>{count+=chunk.byteLength;chunks.push(chunk);item.count=count;});
  request.on('aborted',()=>{item.aborted=true;});
  request.on('error',()=>{});
  request.on('end',()=>{item.sha256=createHash('sha256').update(Buffer.concat(chunks)).digest('hex');response.writeHead(200,{'content-type':'application/json'});response.end(JSON.stringify(item));});
 });
 let mf;let root;
 try {
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  root=await mkdtemp(join(tmpdir(),'sg-native-import-test-'));
  const bundle=await build({stdin:{contents:`
    import {importCipherStream} from './recovery-io.ts';
    export default {async fetch(request,env){
      const mode=new URL(request.url).pathname.slice(1);
      const bytes=new Uint8Array(mode==='short'?12:mode==='long'?14:13);for(let i=0;i<bytes.length;i++)bytes[i]=i;
      const source=new ReadableStream({start(c){c.enqueue(bytes);c.close();}});
      try {
        const receipt=await importCipherStream(source,13,async(body,signal)=>{
          const response=await fetch(env.RECEIVER_URL,{method:'POST',body,signal,headers:{'Content-Type':'application/vnd.sg.cipher-export+v1'}});
          if(response.status!==200)throw new Error('held');return response.json();
        },new AbortController().signal,3000);
        return Response.json({state:'verified',receipt});
      }catch {return Response.json({state:'held'},{status:503});}
    }};`,resolveDir:dirname(fileURLToPath(import.meta.url)),sourcefile:'native-import-test.ts',loader:'ts'},bundle:true,format:'esm',platform:'browser',write:false});
  mf=new Miniflare(convertV4MiniflareOptions({name:'synthetic-fixed-import',modules:true,script:bundle.outputFiles[0].text,compatibilityDate:'2026-10-05',bindings:{RECEIVER_URL:`http://127.0.0.1:${server.address().port}/_management/import`},resourcePersistencePath:root,isolatedResourcePersistencePath:root}));
  const exact=await mf.dispatchFetch('https://synthetic.test/exact');assert.equal(exact.status,200);const result=await exact.json();assert.equal(result.state,'verified');assert.equal(result.receipt.length,'13');assert.equal(result.receipt.transfer,null);assert.equal(result.receipt.count,13);assert.equal(result.receipt.sha256,createHash('sha256').update(Uint8Array.from({length:13},(_,i)=>i)).digest('hex'));
  for(const mode of ['short','long']){const response=await mf.dispatchFetch(`https://synthetic.test/${mode}`);assert.equal(response.status,503);assert.deepEqual(await response.json(),{state:'held'});}
  assert.ok(observations.every(o=>o.length==='13' && o.transfer===null));
 } finally {
  if(mf)await mf.dispose();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));if(root)await rm(root,{recursive:true,force:true});
 }
});
