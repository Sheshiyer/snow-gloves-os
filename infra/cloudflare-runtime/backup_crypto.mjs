import crypto from 'node:crypto';
import { types } from 'node:util';

const MAGIC = Buffer.from('SGBK0001', 'ascii'); // 8 bytes
const MAGIC_LEN = 8;
const META_LEN_SIZE = 4;
const NONCE_LEN = 12;
const TAG_LEN = 16;
const MAX_META_LEN = 4096;
const MIN_PLAINTEXT_LEN = 1;
const MAX_PLAINTEXT_LEN = 64 * 1024 * 1024; // 64 MiB
const MAX_ENVELOPE_LEN = MAX_PLAINTEXT_LEN + MAX_META_LEN + 40;

const REQUIRED_RUNTIME_VERSION = '3.8.50';
const IMAGE_DIGEST_REGEX = /^[0-9a-f]{64}$/;
const KEY_ID_REGEX = /^[0-9a-z-]{1,64}$/;

const GENERIC_ERROR_MESSAGE = 'Backup cryptographic operation failed';

function fail() {
  throw new Error(GENERIC_ERROR_MESSAGE);
}

function validateKey(key) {
  if (!Buffer.isBuffer(key) || key.length !== 32) {
    fail();
  }
}

function isPlainObject(obj) {
  if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
    return false;
  }
  const proto = Object.getPrototypeOf(obj);
  return proto === Object.prototype || proto === null;
}

function validateContext(context) {
  if (!isPlainObject(context) || types.isProxy(context)) {
    fail();
  }
  const keys = Reflect.ownKeys(context);
  if (keys.length !== 3) {
    fail();
  }
  const requiredKeys = ['runtimeVersion', 'imageDigest', 'keyId'];
  for (const k of requiredKeys) {
    if (!Object.prototype.hasOwnProperty.call(context, k)) {
      fail();
    }
    const descriptor = Object.getOwnPropertyDescriptor(context, k);
    if (!descriptor || !Object.hasOwn(descriptor, 'value') || !descriptor.enumerable) {
      fail();
    }
  }
  if (context.runtimeVersion !== REQUIRED_RUNTIME_VERSION) {
    fail();
  }
  if (typeof context.imageDigest !== 'string' || !IMAGE_DIGEST_REGEX.test(context.imageDigest)) {
    fail();
  }
  if (typeof context.keyId !== 'string' || !KEY_ID_REGEX.test(context.keyId)) {
    fail();
  }
}

function buildCanonicalJson(metadata) {
  return JSON.stringify({
    formatVersion: metadata.formatVersion,
    runtimeVersion: metadata.runtimeVersion,
    imageDigest: metadata.imageDigest,
    keyId: metadata.keyId,
    plaintextLength: metadata.plaintextLength
  });
}

export function encryptBackup(plaintext, key, context) {
  try {
    validateKey(key);
    if (!Buffer.isBuffer(plaintext) || plaintext.length < MIN_PLAINTEXT_LEN || plaintext.length > MAX_PLAINTEXT_LEN) {
      fail();
    }
    validateContext(context);

    const metadataObj = {
      formatVersion: 1,
      runtimeVersion: context.runtimeVersion,
      imageDigest: context.imageDigest,
      keyId: context.keyId,
      plaintextLength: plaintext.length
    };

    const canonicalStr = buildCanonicalJson(metadataObj);
    const metaBuf = Buffer.from(canonicalStr, 'utf8');
    if (metaBuf.length > MAX_META_LEN) {
      fail();
    }

    const metaLenBuf = Buffer.allocUnsafe(4);
    metaLenBuf.writeUInt32BE(metaBuf.length, 0);

    const aad = Buffer.concat([MAGIC, metaLenBuf, metaBuf]);
    const nonce = crypto.randomBytes(NONCE_LEN);

    const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce, { authTagLength: TAG_LEN });
    cipher.setAAD(aad);
    const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
    const authTag = cipher.getAuthTag();

    return Buffer.concat([aad, nonce, ciphertext, authTag]);
  } catch (err) {
    fail();
  }
}

export function decryptBackup(envelope, key, expectedContext) {
  try {
    validateKey(key);
    validateContext(expectedContext);
    if (!Buffer.isBuffer(envelope)) {
      fail();
    }
    if (envelope.length > MAX_ENVELOPE_LEN) {
      fail();
    }

    const minHeaderLen = MAGIC_LEN + META_LEN_SIZE + NONCE_LEN + TAG_LEN;
    if (envelope.length < minHeaderLen) {
      fail();
    }

    if (!envelope.subarray(0, MAGIC_LEN).equals(MAGIC)) {
      fail();
    }

    const metaLen = envelope.readUInt32BE(MAGIC_LEN);
    if (metaLen <= 0 || metaLen > MAX_META_LEN) {
      fail();
    }

    const metaStart = MAGIC_LEN + META_LEN_SIZE;
    const metaEnd = metaStart + metaLen;
    if (envelope.length < metaEnd + NONCE_LEN + TAG_LEN) {
      fail();
    }

    const metaBuf = envelope.subarray(metaStart, metaEnd);
    const metaStr = metaBuf.toString('utf8');

    // Verify utf8 round-trip
    if (!Buffer.from(metaStr, 'utf8').equals(metaBuf)) {
      fail();
    }

    let parsed;
    try {
      parsed = JSON.parse(metaStr);
    } catch {
      fail();
    }

    if (!isPlainObject(parsed)) {
      fail();
    }

    const metaKeys = Object.keys(parsed);
    const expectedKeys = ['formatVersion', 'runtimeVersion', 'imageDigest', 'keyId', 'plaintextLength'];
    if (metaKeys.length !== expectedKeys.length) {
      fail();
    }
    for (let i = 0; i < expectedKeys.length; i++) {
      if (metaKeys[i] !== expectedKeys[i]) {
        fail();
      }
    }

    if (parsed.formatVersion !== 1) {
      fail();
    }
    if (parsed.runtimeVersion !== expectedContext.runtimeVersion) {
      fail();
    }
    if (parsed.imageDigest !== expectedContext.imageDigest) {
      fail();
    }
    if (parsed.keyId !== expectedContext.keyId) {
      fail();
    }
    if (typeof parsed.plaintextLength !== 'number' || !Number.isSafeInteger(parsed.plaintextLength)) {
      fail();
    }
    if (parsed.plaintextLength < MIN_PLAINTEXT_LEN || parsed.plaintextLength > MAX_PLAINTEXT_LEN) {
      fail();
    }

    const canonicalReconstructed = buildCanonicalJson(parsed);
    if (canonicalReconstructed !== metaStr) {
      fail();
    }

    const nonceStart = metaEnd;
    const nonceEnd = nonceStart + NONCE_LEN;
    const nonce = envelope.subarray(nonceStart, nonceEnd);

    const expectedTotalLen = metaEnd + NONCE_LEN + parsed.plaintextLength + TAG_LEN;
    if (envelope.length !== expectedTotalLen) {
      fail();
    }

    const ciphertextStart = nonceEnd;
    const ciphertextEnd = ciphertextStart + parsed.plaintextLength;
    const ciphertext = envelope.subarray(ciphertextStart, ciphertextEnd);
    const authTag = envelope.subarray(ciphertextEnd, ciphertextEnd + TAG_LEN);

    const aad = envelope.subarray(0, metaEnd);

    const decipher = crypto.createDecipheriv('aes-256-gcm', key, nonce, { authTagLength: TAG_LEN });
    decipher.setAAD(aad);
    decipher.setAuthTag(authTag);

    const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    if (decrypted.length !== parsed.plaintextLength) {
      fail();
    }

    return decrypted;
  } catch (err) {
    fail();
  }
}
