import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes, createDecipheriv } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { encryptBackup, decryptBackup } from './backup_crypto.mjs';

const key = randomBytes(32);
const context = { runtimeVersion: '3.8.50', imageDigest: 'a'.repeat(64), keyId: 'fixture-backup-key' };
const plaintext = Buffer.from('SQLite format 3\0owned recognizable synthetic value');
const envelope = encryptBackup(plaintext, key, context);
const metadataEnd = 12 + envelope.readUInt32BE(8);
const deny = operation => assert.throws(operation, { message: 'Backup cryptographic operation failed' });
const mutate = offset => { const changed = Buffer.from(envelope); changed[offset] ^= 1; return changed; };

test('real SQLite roundtrip and tamper preserves source file bytes', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'sg-crypto-sqlite-'));
  try {
    const file = path.join(dir, 'fixture.sqlite');
    const result = spawnSync('python3', ['-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("create table proof(value text)"); c.execute("insert into proof values (?)",("owned recognizable synthetic value",)); c.commit(); c.close()', file]);
    assert.equal(result.status, 0);
    const before = readFileSync(file);
    const sealed = encryptBackup(before, key, context);
    assert.ok(!sealed.includes(Buffer.from('SQLite format 3')));
    assert.ok(!sealed.includes(Buffer.from('owned recognizable synthetic value')));
    assert.deepEqual(decryptBackup(sealed, key, context), before);
    const broken = Buffer.from(sealed); broken[broken.length-1] ^= 1;
    deny(() => decryptBackup(broken, key, context));
    assert.deepEqual(readFileSync(file), before);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test('independent Node decipher verifies envelope authentication and plaintext', () => {
  const decipher = createDecipheriv('aes-256-gcm', key, envelope.subarray(metadataEnd,metadataEnd+12), {authTagLength:16});
  decipher.setAAD(envelope.subarray(0,metadataEnd));
  decipher.setAuthTag(envelope.subarray(-16));
  assert.deepEqual(Buffer.concat([decipher.update(envelope.subarray(metadataEnd+12,-16)),decipher.final()]), plaintext);
});
test('fresh nonce differs for identical plaintext', () => {
  const second = encryptBackup(plaintext,key,context);
  assert.notDeepEqual(envelope.subarray(metadataEnd,metadataEnd+12),second.subarray(metadataEnd,metadataEnd+12));
});
for (const [name,offset] of [['magic',0],['metadata',25],['nonce',metadataEnd],['ciphertext',metadataEnd+12],['tag',envelope.length-1]]) {
  test(`${name} tampering rejected`, () => deny(() => decryptBackup(mutate(offset),key,context)));
}
test('wrong key rejected',()=>deny(()=>decryptBackup(envelope,randomBytes(32),context)));
for (const [name,value] of [['runtimeVersion','3.8.51'],['imageDigest','b'.repeat(64)],['keyId','different-key']]) {
  test(`${name} mismatch rejected`,()=>deny(()=>decryptBackup(envelope,key,{...context,[name]:value})));
}
for (const length of [0,1,31,33]) test(`key length ${length} rejected`,()=>deny(()=>encryptBackup(plaintext,Buffer.alloc(length),context)));
test('key Uint8Array rejected',()=>deny(()=>encryptBackup(plaintext,new Uint8Array(32),context)));
test('plaintext Uint8Array rejected',()=>deny(()=>encryptBackup(new Uint8Array(1),key,context)));
test('empty plaintext rejected',()=>deny(()=>encryptBackup(Buffer.alloc(0),key,context)));
test('plaintext above64MiB rejected',()=>deny(()=>encryptBackup(Buffer.alloc(64*1024*1024+1),key,context)));
test('full64MiB plaintext encrypts and decrypts at the supported boundary',()=>{
  const input=Buffer.alloc(64*1024*1024,0x5a);
  const sealed=encryptBackup(input,key,context);
  const restored=decryptBackup(sealed,key,context);
  assert.equal(restored.length,input.length);
  assert.ok(restored.equals(input));
});
test('unknown context field rejected',()=>deny(()=>encryptBackup(plaintext,key,{...context,unexpected:true})));
test('inherited required fields rejected',()=>deny(()=>encryptBackup(plaintext,key,Object.create(context))));
test('nonenumerable unknown context field rejected',()=>{const changed={...context};Object.defineProperty(changed,'unexpected',{value:true});deny(()=>encryptBackup(plaintext,key,changed));});
test('symbol context field rejected',()=>{const changed={...context,[Symbol('unexpected')]:true};deny(()=>encryptBackup(plaintext,key,changed));});
test('accessor context field rejected',()=>{const changed={...context};Object.defineProperty(changed,'keyId',{get:()=>context.keyId,enumerable:true});deny(()=>encryptBackup(plaintext,key,changed));});
test('rejected accessor is never invoked',()=>{let calls=0;const changed={...context};Object.defineProperty(changed,'keyId',{get:()=>{calls++;return context.keyId},enumerable:true});deny(()=>encryptBackup(plaintext,key,changed));assert.equal(calls,0);});
test('nonenumerable required field rejected',()=>{const changed={...context};Object.defineProperty(changed,'keyId',{value:context.keyId,enumerable:false});deny(()=>encryptBackup(plaintext,key,changed));});
test('proxy context rejected',()=>deny(()=>encryptBackup(plaintext,key,new Proxy(context,{}))));
test('array context rejected',()=>deny(()=>encryptBackup(plaintext,key,[])));
test('truncated envelope rejected',()=>deny(()=>decryptBackup(envelope.subarray(0,-1),key,context)));
test('trailing envelope bytes rejected',()=>deny(()=>decryptBackup(Buffer.concat([envelope,Buffer.from([0])]),key,context)));
test('metadata length0 rejected',()=>{const changed=Buffer.from(envelope);changed.writeUInt32BE(0,8);deny(()=>decryptBackup(changed,key,context));});
test('metadata above4096 rejected',()=>{const changed=Buffer.from(envelope);changed.writeUInt32BE(4097,8);deny(()=>decryptBackup(changed,key,context));});
function replaceMetadata(text) {
  const bytes=Buffer.from(text);const len=Buffer.alloc(4);len.writeUInt32BE(bytes.length);
  return Buffer.concat([envelope.subarray(0,8),len,bytes,envelope.subarray(metadataEnd)]);
}
const metadataText=envelope.subarray(12,metadataEnd).toString('utf8');
test('noncanonical metadata rejected',()=>deny(()=>decryptBackup(replaceMetadata(metadataText+' '),key,context)));
test('duplicate metadata key rejected',()=>deny(()=>decryptBackup(replaceMetadata(metadataText.replace('"formatVersion":1,','"formatVersion":1,"formatVersion":1,')),key,context)));
test('unsupported format version rejected',()=>deny(()=>decryptBackup(replaceMetadata(metadataText.replace('"formatVersion":1','"formatVersion":2')),key,context)));
test('oversize declared plaintext rejected',()=>deny(()=>decryptBackup(replaceMetadata(metadataText.replace(/"plaintextLength":\d+/, '"plaintextLength":67108865')),key,context)));
test('invalid UTF8 rejected',()=>{const changed=Buffer.from(envelope);changed[15]=0xff;deny(()=>decryptBackup(changed,key,context));});
