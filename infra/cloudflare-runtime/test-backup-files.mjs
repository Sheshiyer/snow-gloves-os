import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { runFileOperation } from './backup_file_cli.mjs';
if (os.platform() !== 'linux' || Number(process.versions.node.split('.')[0]) < 24) {
  throw new Error('Backup file checks require Linux and Node 24 or later');
}
const fixtureOwnedDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sg-file-test-fixture-'));
const fixtureDatabase = process.env.SG_FILE_SQLITE_FIXTURE || path.join(fixtureOwnedDir, 'fixture.sqlite');
if (!process.env.SG_FILE_SQLITE_FIXTURE) {
  const built = spawnSync('python3', ['-c',
    "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('CREATE TABLE owned_fixture(value TEXT)'); c.execute('INSERT INTO owned_fixture VALUES (?)', ('synthetic test fixture',)); c.commit(); c.close()",
    fixtureDatabase], { encoding: 'utf8' });
  assert.equal(built.status, 0, 'Synthetic SQLite fixture requires Python3');
  fs.chmodSync(fixtureDatabase, 0o600);
}
after(() => fs.rmSync(fixtureOwnedDir, { recursive: true, force: true }));
const generic = { message: 'Backup file operation failed' };
function setup() {
  const parent=fs.mkdtempSync(path.join(os.tmpdir(),'sg-file-review-'));
  const root=path.join(parent,'data');fs.mkdirSync(root,{mode:0o700});
  fs.writeFileSync(path.join(root,'snapshot.sqlite'),fs.readFileSync(fixtureDatabase),{mode:0o600});
  return {parent,root,options:{mode:'encrypt',inputLeaf:'snapshot.sqlite',outputLeaf:'sealed.bin',rootPath:root,base64Key:randomBytes(32).toString('base64'),imageDigest:'a'.repeat(64),keyId:'fixture-key'}};
}
async function owned(work) {const fixture=setup();try{await work(fixture)}finally{fs.rmSync(fixture.parent,{recursive:true,force:true});}}
test('actual owned-file encryption and decryption roundtrip',()=>owned(async f=>{
  const result=await runFileOperation(f.options);assert.equal(result.output,'sealed.bin');assert.equal(fs.statSync(path.join(f.root,'sealed.bin')).mode&0o777,0o600);
  await runFileOperation({...f.options,mode:'decrypt',inputLeaf:'sealed.bin',outputLeaf:'restored.sqlite'});
  assert.deepEqual(fs.readFileSync(path.join(f.root,'restored.sqlite')),fs.readFileSync(path.join(f.root,'snapshot.sqlite')));
}));
test('existing output remains byte-identical on no-clobber denial',()=>owned(async f=>{
  fs.writeFileSync(path.join(f.root,'sealed.bin'),'unrelated',{mode:0o600});await assert.rejects(runFileOperation(f.options),generic);assert.equal(fs.readFileSync(path.join(f.root,'sealed.bin'),'utf8'),'unrelated');
}));
test('wrong key creates no plaintext output',()=>owned(async f=>{
  await runFileOperation(f.options);await assert.rejects(runFileOperation({...f.options,mode:'decrypt',inputLeaf:'sealed.bin',outputLeaf:'restored.sqlite',base64Key:randomBytes(32).toString('base64')}),generic);assert.equal(fs.existsSync(path.join(f.root,'restored.sqlite')),false);
}));
test('input symlink denied',()=>owned(async f=>{
  fs.symlinkSync('snapshot.sqlite',path.join(f.root,'link.sqlite'));await assert.rejects(runFileOperation({...f.options,inputLeaf:'link.sqlite'}),generic);
}));
test('input hardlink denied',()=>owned(async f=>{
  fs.linkSync(path.join(f.root,'snapshot.sqlite'),path.join(f.root,'hard.sqlite'));await assert.rejects(runFileOperation(f.options),generic);
}));
test('group-readable input denied',()=>owned(async f=>{
  fs.chmodSync(path.join(f.root,'snapshot.sqlite'),0o640);await assert.rejects(runFileOperation(f.options),generic);
}));
test('traversal leaf denied',()=>owned(async f=>assert.rejects(runFileOperation({...f.options,outputLeaf:'../outside.bin'}),generic)));
test('root symlink denied',()=>owned(async f=>{
  const alias=path.join(f.parent,'alias');fs.symlinkSync(f.root,alias);await assert.rejects(runFileOperation({...f.options,rootPath:alias}),generic);
}));
test('directory fsync failure cannot return success acknowledgment',()=>owned(async f=>{
  const original=fs.fsyncSync;fs.fsyncSync=fd=>{if(fs.fstatSync(fd).isDirectory())throw new Error('owned injected directory fsync failure');return original(fd)};
  try{await assert.rejects(runFileOperation(f.options),generic);assert.equal(fs.existsSync(path.join(f.root,'sealed.bin')),true)}finally{fs.fsyncSync=original}
}));
test('root replaced by symlink to original inode is held before publication',()=>owned(async f=>{
  const original=fs.fsyncSync;let moved=false;fs.fsyncSync=fd=>{if(!fs.fstatSync(fd).isDirectory()&&!moved){moved=true;fs.renameSync(f.root,f.root+'-old');fs.symlinkSync(f.root+'-old',f.root)}return original(fd)};
  try{await assert.rejects(runFileOperation(f.options),generic);assert.equal(moved,true)}finally{fs.fsyncSync=original}
}));
test('temporary unlink failure cannot return success acknowledgment',()=>owned(async f=>{
  const original=fs.unlinkSync;fs.unlinkSync=filename=>{if(String(filename).includes('.tmp_backup_'))throw new Error('owned injected unlink failure');return original(filename)};
  try{await assert.rejects(runFileOperation(f.options),generic)}finally{fs.unlinkSync=original}
}));
test('null library options fail with redacted generic error',()=>assert.rejects(runFileOperation(null),generic));
const cli=fileURLToPath(new URL('./backup_file_cli.mjs',import.meta.url));
function cliEnvironment(f){return {SG_BACKUP_ROOT:f.root,SG_BACKUP_KEY:f.options.base64Key,SG_BACKUP_IMAGE:f.options.imageDigest,SG_BACKUP_KEY_ID:f.options.keyId};}
test('actual CLI encrypt/decrypt emits only successful metadata',()=>owned(async f=>{
  const first=spawnSync(process.execPath,[cli,'encrypt','snapshot.sqlite','sealed.bin'],{env:cliEnvironment(f),encoding:'utf8'});
  assert.equal(first.status,0);assert.equal(first.stderr,'');const metadata=JSON.parse(first.stdout);assert.deepEqual(Object.keys(metadata).sort(),['bytes','mode','output','sha256']);assert.ok(!first.stdout.includes(f.options.base64Key));
  const second=spawnSync(process.execPath,[cli,'decrypt','sealed.bin','restored.sqlite'],{env:cliEnvironment(f),encoding:'utf8'});assert.equal(second.status,0);assert.equal(second.stderr,'');
  assert.deepEqual(fs.readFileSync(path.join(f.root,'restored.sqlite')),fs.readFileSync(path.join(f.root,'snapshot.sqlite')));
}));
test('actual CLI missing key fails with generic stderr and no output',()=>owned(async f=>{
  const env=cliEnvironment(f);delete env.SG_BACKUP_KEY;const result=spawnSync(process.execPath,[cli,'encrypt','snapshot.sqlite','sealed.bin'],{env,encoding:'utf8'});assert.equal(result.status,1);assert.equal(result.stdout,'');assert.equal(result.stderr,'Backup file operation failed\n');assert.equal(fs.existsSync(path.join(f.root,'sealed.bin')),false);
}));
test('actual CLI wrong key preserves ciphertext and creates no plaintext',()=>owned(async f=>{
  await runFileOperation(f.options);const before=fs.readFileSync(path.join(f.root,'sealed.bin'));const env={...cliEnvironment(f),SG_BACKUP_KEY:randomBytes(32).toString('base64')};const result=spawnSync(process.execPath,[cli,'decrypt','sealed.bin','restored.sqlite'],{env,encoding:'utf8'});assert.equal(result.status,1);assert.equal(result.stdout,'');assert.equal(result.stderr,'Backup file operation failed\n');assert.equal(fs.existsSync(path.join(f.root,'restored.sqlite')),false);assert.deepEqual(fs.readFileSync(path.join(f.root,'sealed.bin')),before);
}));
test('actual CLI invalid argument count fails generically',()=>owned(async f=>{
  const result=spawnSync(process.execPath,[cli,'encrypt','snapshot.sqlite'],{env:cliEnvironment(f),encoding:'utf8'});assert.equal(result.status,1);assert.equal(result.stdout,'');assert.equal(result.stderr,'Backup file operation failed\n');
}));

test('temporary inode replacement before publication must deny success',()=>owned(async f=>{
  const original=fs.linkSync;let swapped=false;
  fs.linkSync=(from,to)=>{if(String(from).includes('.tmp_backup_')){fs.renameSync(from,path.join(f.root,'owned-original.tmp'));fs.writeFileSync(from,'substituted bytes',{mode:0o600});swapped=true;}return original(from,to);};
  try {await assert.rejects(runFileOperation(f.options),generic);assert.equal(swapped,true);} finally {fs.linkSync=original;}
}));

test('temporary same-inode byte replacement must deny success',()=>owned(async f=>{
 const original=fs.linkSync;let changed=false;fs.linkSync=(from,to)=>{if(String(from).includes('.tmp_backup_')){fs.writeFileSync(from,'same inode substituted bytes');changed=true;}return original(from,to);};
 try{await assert.rejects(runFileOperation(f.options),generic);assert.equal(changed,true);}finally{fs.linkSync=original;}
}));

test('actual CLI interruption before publication leaves no success or final output',()=>owned(async f=>{
 const preload=path.join(f.parent,'interrupt-before.mjs');fs.writeFileSync(preload,"import fs from 'node:fs';const original=fs.fsyncSync;fs.fsyncSync=fd=>{if(!fs.fstatSync(fd).isDirectory())process.kill(process.pid,'SIGKILL');return original(fd)};");
 const before=fs.readFileSync(path.join(f.root,'snapshot.sqlite'));const result=spawnSync(process.execPath,['--import',preload,cli,'encrypt','snapshot.sqlite','sealed.bin'],{env:cliEnvironment(f),encoding:'utf8'});assert.equal(result.signal,'SIGKILL');assert.equal(result.stdout,'');assert.equal(fs.existsSync(path.join(f.root,'sealed.bin')),false);assert.deepEqual(fs.readFileSync(path.join(f.root,'snapshot.sqlite')),before);assert.ok(fs.readdirSync(f.root).some(name=>name.startsWith('.tmp_backup_')));
}));
test('actual CLI interruption after publication leaves authenticated output without success receipt',()=>owned(async f=>{
 const preload=path.join(f.parent,'interrupt-after.mjs');fs.writeFileSync(preload,"import fs from 'node:fs';const original=fs.fsyncSync;fs.fsyncSync=fd=>{if(fs.fstatSync(fd).isDirectory())process.kill(process.pid,'SIGKILL');return original(fd)};");
 const result=spawnSync(process.execPath,['--import',preload,cli,'encrypt','snapshot.sqlite','sealed.bin'],{env:cliEnvironment(f),encoding:'utf8'});assert.equal(result.signal,'SIGKILL');assert.equal(result.stdout,'');assert.ok(fs.existsSync(path.join(f.root,'sealed.bin')));await runFileOperation({...f.options,mode:'decrypt',inputLeaf:'sealed.bin',outputLeaf:'restored.sqlite'});assert.deepEqual(fs.readFileSync(path.join(f.root,'restored.sqlite')),fs.readFileSync(path.join(f.root,'snapshot.sqlite')));
}));

test('actual input bytes mutated during read deny publication',()=>owned(async f=>{
 const original=fs.readSync;let changed=false;fs.readSync=(...args)=>{const count=original(...args);if(!changed&&count>1){changed=true;const file=path.join(f.root,'snapshot.sqlite');const bytes=fs.readFileSync(file);bytes[50]^=1;fs.writeFileSync(file,bytes);}return count;};
 try{await assert.rejects(runFileOperation(f.options),generic);assert.equal(changed,true);assert.equal(fs.existsSync(path.join(f.root,'sealed.bin')),false);}finally{fs.readSync=original;}
}));
test('actual input growth during read denies publication',()=>owned(async f=>{
 const original=fs.readSync;let changed=false;fs.readSync=(...args)=>{const count=original(...args);if(!changed&&count>1){changed=true;fs.appendFileSync(path.join(f.root,'snapshot.sqlite'),'growth');}return count;};
 try{await assert.rejects(runFileOperation(f.options),generic);assert.equal(changed,true);assert.equal(fs.existsSync(path.join(f.root,'sealed.bin')),false);}finally{fs.readSync=original;}
}));

test('input mutation denied even when filesystem timestamp observations are unchanged',()=>owned(async f=>{
 const originalRead=fs.readSync,originalStat=fs.fstatSync;let before=null,changed=false;
 fs.fstatSync=(fd,options)=>{const stat=originalStat(fd,options);if(fs.realpathSync('/proc/self/fd/'+fd)===path.join(f.root,'snapshot.sqlite')){if(!before)before=stat;else{stat.mtimeNs=before.mtimeNs;stat.ctimeNs=before.ctimeNs;}}return stat;};
 fs.readSync=(...args)=>{const count=originalRead(...args);if(!changed&&count>1){changed=true;const file=path.join(f.root,'snapshot.sqlite');const bytes=fs.readFileSync(file);bytes[50]^=1;fs.writeFileSync(file,bytes);}return count;};
 try{await assert.rejects(runFileOperation(f.options),generic);assert.equal(changed,true);assert.equal(fs.existsSync(path.join(f.root,'sealed.bin')),false);}finally{fs.readSync=originalRead;fs.fstatSync=originalStat;}
}));
test('zero-byte temporary write denies publication and cleans only owned temporary',()=>owned(async f=>{
 const original=fs.writeSync;fs.writeSync=()=>0;try{await assert.rejects(runFileOperation(f.options),generic);assert.deepEqual(fs.readdirSync(f.root),['snapshot.sqlite']);}finally{fs.writeSync=original;}
}));
test('temporary file fsync failure denies publication and cleans owned temporary',()=>owned(async f=>{
 const original=fs.fsyncSync;fs.fsyncSync=fd=>{if(!fs.fstatSync(fd).isDirectory())throw new Error('owned injected file sync failure');return original(fd);};try{await assert.rejects(runFileOperation(f.options),generic);assert.deepEqual(fs.readdirSync(f.root),['snapshot.sqlite']);}finally{fs.fsyncSync=original;}
}));
