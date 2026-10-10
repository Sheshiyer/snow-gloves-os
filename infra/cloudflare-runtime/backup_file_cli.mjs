import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { encryptBackup, decryptBackup } from './backup_crypto.mjs';

const RUNTIME_VERSION = '3.8.50';
const MAX_PLAINTEXT_BYTES = 64 * 1024 * 1024; // 64 MiB
const MAX_ENVELOPE_BYTES = 64 * 1024 * 1024 + 4136; // 64 MiB + 4136
const SQLITE3_HEADER = Buffer.from('SQLite format 3\0', 'utf8');
const LEAF_REGEX = /^[a-zA-Z0-9._-]{1,128}$/;
const IMAGE_DIGEST_REGEX = /^[0-9a-f]{64}$/;
const KEY_ID_REGEX = /^[a-z0-9-]{1,64}$/;

function failOperation() {
  throw new Error('Backup file operation failed');
}

function validateLeaf(leaf) {
  if (typeof leaf !== 'string' || !LEAF_REGEX.test(leaf) || leaf === '.' || leaf === '..') {
    failOperation();
  }
}

function validateBase64Key32(b64) {
  if (typeof b64 !== 'string' || !/^[A-Za-z0-9+/]{43}=$/.test(b64)) {
    failOperation();
  }
  const buf = Buffer.from(b64, 'base64');
  if (buf.length !== 32 || buf.toString('base64') !== b64) {
    failOperation();
  }
  return buf;
}

async function readFileExact(fd, expectedSize) {
  const buffer = Buffer.alloc(expectedSize);
  let totalRead = 0;
  while (totalRead < expectedSize) {
    const bytesRead = fs.readSync(fd, buffer, totalRead, expectedSize - totalRead, totalRead);
    if (bytesRead === 0) {
      failOperation();
    }
    totalRead += bytesRead;
  }
  const probe = Buffer.alloc(1);
  const extra = fs.readSync(fd, probe, 0, 1, totalRead);
  if (extra !== 0) {
    failOperation();
  }
  return buffer;
}

function verifyInputBytes(fd, expected) {
  const chunk = Buffer.alloc(Math.min(65536, expected.length));
  let offset = 0;
  while (offset < expected.length) {
    const count = fs.readSync(fd, chunk, 0, Math.min(chunk.length, expected.length - offset), offset);
    if (count === 0 || !chunk.subarray(0, count).equals(expected.subarray(offset, offset + count))) {
      failOperation();
    }
    offset += count;
  }
  if (fs.readSync(fd, chunk, 0, 1, offset) !== 0) failOperation();
}

export async function runFileOperation(options) {
  let keyBuf = null;
  let rootFd = null;
  let tempPathInProc = null;
  let tempCreated = false;
  let tempIdentity = null;

  try {
  if (!options || typeof options !== 'object' || Array.isArray(options)) {
    failOperation();
  }
  const { mode, inputLeaf, outputLeaf, rootPath, base64Key, imageDigest, keyId } = options;
  if (os.platform() !== 'linux') {
    failOperation();
  }
  if (mode !== 'encrypt' && mode !== 'decrypt') {
    failOperation();
  }
  validateLeaf(inputLeaf);
  validateLeaf(outputLeaf);
  if (inputLeaf === outputLeaf) {
    failOperation();
  }

  if (typeof rootPath !== 'string' || !path.isAbsolute(rootPath)) {
    failOperation();
  }
  if (typeof imageDigest !== 'string' || !IMAGE_DIGEST_REGEX.test(imageDigest)) {
    failOperation();
  }
  if (typeof keyId !== 'string' || !KEY_ID_REGEX.test(keyId)) {
    failOperation();
  }

    keyBuf = validateBase64Key32(base64Key);

    let canonicalRoot;
    try {
      canonicalRoot = fs.realpathSync(rootPath);
    } catch {
      failOperation();
    }
    if (canonicalRoot !== path.resolve(rootPath)) {
      failOperation();
    }

    const rootPreStat = fs.lstatSync(canonicalRoot);
    const euid = process.geteuid();
    if (!rootPreStat.isDirectory() || rootPreStat.isSymbolicLink()) {
      failOperation();
    }
    if (rootPreStat.uid !== euid) {
      failOperation();
    }
    if ((rootPreStat.mode & 0o022) !== 0) {
      failOperation();
    }

    const openFlags = fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW;
    try {
      rootFd = fs.openSync(canonicalRoot, openFlags);
    } catch {
      failOperation();
    }

    const rootFdStat = fs.fstatSync(rootFd);
    if (rootFdStat.dev !== rootPreStat.dev || rootFdStat.ino !== rootPreStat.ino) {
      failOperation();
    }
    if (!rootFdStat.isDirectory() || rootFdStat.uid !== euid || (rootFdStat.mode & 0o022) !== 0) {
      failOperation();
    }

    const inputProcPath = `/proc/self/fd/${rootFd}/${inputLeaf}`;
    let inFd = null;
    let inputBytes;
    try {
      try {
        inFd = fs.openSync(inputProcPath, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
      } catch {
        failOperation();
      }

      const inStatBefore = fs.fstatSync(inFd, { bigint: true });
      if (!inStatBefore.isFile()) {
        failOperation();
      }
      if (inStatBefore.nlink !== 1n) {
        failOperation();
      }
      if (inStatBefore.uid !== BigInt(euid)) {
        failOperation();
      }
      if ((inStatBefore.mode & 0o077n) !== 0n) {
        failOperation();
      }

      const inSize = Number(inStatBefore.size);
      if (inSize <= 0) {
        failOperation();
      }
      if (mode === 'encrypt' && inSize > MAX_PLAINTEXT_BYTES) {
        failOperation();
      }
      if (mode === 'decrypt' && inSize > MAX_ENVELOPE_BYTES) {
        failOperation();
      }

      inputBytes = await readFileExact(inFd, inSize);

      verifyInputBytes(inFd, inputBytes);
      const inStatAfter = fs.fstatSync(inFd, { bigint: true });
      if (
        inStatAfter.dev !== inStatBefore.dev ||
        inStatAfter.ino !== inStatBefore.ino ||
        inStatAfter.size !== inStatBefore.size ||
        inStatAfter.mtimeNs !== inStatBefore.mtimeNs ||
        inStatAfter.ctimeNs !== inStatBefore.ctimeNs ||
        inStatAfter.nlink !== inStatBefore.nlink
      ) {
        failOperation();
      }
    } finally {
      if (inFd !== null) {
        try {
          fs.closeSync(inFd);
        } catch {}
      }
    }

    const cryptoContext = {
      runtimeVersion: RUNTIME_VERSION,
      imageDigest,
      keyId
    };

    let outputBytes;
    if (mode === 'encrypt') {
      if (inputBytes.length < SQLITE3_HEADER.length || !inputBytes.subarray(0, SQLITE3_HEADER.length).equals(SQLITE3_HEADER)) {
        failOperation();
      }
      try {
        outputBytes = encryptBackup(inputBytes, keyBuf, cryptoContext);
      } catch {
        failOperation();
      }
      if (!Buffer.isBuffer(outputBytes) || outputBytes.length > MAX_ENVELOPE_BYTES) {
        failOperation();
      }
    } else {
      try {
        outputBytes = decryptBackup(inputBytes, keyBuf, cryptoContext);
      } catch {
        failOperation();
      }
      if (!Buffer.isBuffer(outputBytes) || outputBytes.length > MAX_PLAINTEXT_BYTES) {
        failOperation();
      }
      if (outputBytes.length < SQLITE3_HEADER.length || !outputBytes.subarray(0, SQLITE3_HEADER.length).equals(SQLITE3_HEADER)) {
        failOperation();
      }
    }

    const tempLeaf = `.tmp_backup_${process.pid}_${crypto.randomBytes(16).toString('hex')}`;
    tempPathInProc = `/proc/self/fd/${rootFd}/${tempLeaf}`;

    const tempFlags = fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW;
    let tempFd = null;
    try {
      tempFd = fs.openSync(tempPathInProc, tempFlags, 0o600);
      tempCreated = true;
      tempIdentity = fs.fstatSync(tempFd, { bigint: true });
    } catch {
      failOperation();
    }

    try {
      let written = 0;
      while (written < outputBytes.length) {
        const bytesWritten = fs.writeSync(tempFd, outputBytes, written, outputBytes.length - written, written);
        if (bytesWritten === 0) {
          failOperation();
        }
        written += bytesWritten;
      }
      fs.fsyncSync(tempFd);
    } finally {
      try {
        fs.closeSync(tempFd);
      } catch {}
    }

    let checkStat;
    try {
      checkStat = fs.lstatSync(canonicalRoot);
      if (fs.realpathSync(canonicalRoot) !== canonicalRoot || checkStat.isSymbolicLink() ||
          !checkStat.isDirectory() || checkStat.uid !== euid || (checkStat.mode & 0o022) !== 0) {
        failOperation();
      }
    } catch {
      failOperation();
    }
    if (checkStat.dev !== rootFdStat.dev || checkStat.ino !== rootFdStat.ino) {
      failOperation();
    }

    const outPathInProc = `/proc/self/fd/${rootFd}/${outputLeaf}`;
    try {
      fs.linkSync(tempPathInProc, outPathInProc);
    } catch {
      failOperation();
    }

    // Validate the object actually published, not only the buffered bytes.
    // Leave a disputed output for the caller's reconciliation; never acknowledge it.
    let publishedFd = null;
    try {
      publishedFd = fs.openSync(outPathInProc, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
      const before = fs.fstatSync(publishedFd, { bigint: true });
      if (!before.isFile() || before.dev !== BigInt(tempIdentity.dev) ||
          before.ino !== BigInt(tempIdentity.ino) || before.uid !== BigInt(euid) ||
          (before.mode & 0o777n) !== 0o600n || before.nlink !== 2n ||
          before.size !== BigInt(outputBytes.length)) failOperation();
      const published = await readFileExact(publishedFd, outputBytes.length);
      if (!published.equals(outputBytes)) failOperation();
      const after = fs.fstatSync(publishedFd, { bigint: true });
      if (after.size !== before.size || after.mtimeNs !== before.mtimeNs ||
          after.ctimeNs !== before.ctimeNs || after.nlink !== before.nlink) failOperation();
      const temporary = fs.lstatSync(tempPathInProc, { bigint: true });
      const output = fs.lstatSync(outPathInProc, { bigint: true });
      if (!temporary.isFile() || temporary.dev !== before.dev || temporary.ino !== before.ino ||
          !output.isFile() || output.dev !== before.dev || output.ino !== before.ino) failOperation();
    } finally {
      if (publishedFd !== null) fs.closeSync(publishedFd);
    }

    try {
      fs.unlinkSync(tempPathInProc);
      tempCreated = false;
    } catch {
      failOperation();
    }

    try {
      fs.fsyncSync(rootFd);
    } catch {
      failOperation();
    }

    const sha256 = crypto.createHash('sha256').update(outputBytes).digest('hex');
    return {
      mode,
      output: outputLeaf,
      bytes: outputBytes.length,
      sha256
    };
  } catch (err) {
    if (tempCreated && tempPathInProc && tempIdentity) {
      try {
        const current = fs.lstatSync(tempPathInProc, { bigint: true });
        if (current.isFile() && current.uid === tempIdentity.uid &&
            current.dev === tempIdentity.dev && current.ino === tempIdentity.ino) {
          fs.unlinkSync(tempPathInProc);
        }
      } catch {}
    }
    failOperation();
  } finally {
    if (keyBuf) {
      keyBuf.fill(0);
    }
    if (rootFd !== null) {
      try {
        fs.closeSync(rootFd);
      } catch {}
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  (async () => {
    const args = process.argv.slice(2);
    if (args.length !== 3) {
      process.stderr.write('Backup file operation failed\n');
      process.exit(1);
    }
    const [mode, inputLeaf, outputLeaf] = args;
    const rootPath = process.env.SG_BACKUP_ROOT;
    const base64Key = process.env.SG_BACKUP_KEY;
    const imageDigest = process.env.SG_BACKUP_IMAGE;
    const keyId = process.env.SG_BACKUP_KEY_ID;

    if (!rootPath || !base64Key || !imageDigest || !keyId) {
      process.stderr.write('Backup file operation failed\n');
      process.exit(1);
    }

    try {
      const result = await runFileOperation({
        mode,
        inputLeaf,
        outputLeaf,
        rootPath,
        base64Key,
        imageDigest,
        keyId
      });
      process.stdout.write(JSON.stringify(result) + '\n');
    } catch {
      process.stderr.write('Backup file operation failed\n');
      process.exit(1);
    }
  })();
}
