# Isolated OmniRoute runtime image

Build the pinned published OmniRoute 3.8.50 package and its production dependency set for Linux/amd64:

```sh
docker build --platform linux/amd64 -t snowgloves-runtime:3.8.50 infra/cloudflare-runtime
```

The image runs the package server directly under `tini` as the non-root `node` user. It requires a nonempty `STORAGE_ENCRYPTION_KEY` supplied at runtime and an owned writable `/data` directory. Keep the key independently recoverable; it protects credential fields rather than encrypting the entire SQLite backup. Never put real credentials in build arguments, image layers or source files.

The health check requires HTTP 200 and the literal `ok` response from `/healthz`. This proves service lifecycle only, not authentication, provider availability or inference. No provider connection is bundled.

On 2026-10-05 an isolated Linux/amd64 image build passed with a 6 GiB build VM and bounded 2 GiB npm heap; the earlier 3 GiB build exhausted memory. The resulting image measured 1,225,676,445 bytes. Actual startup returned HTTP 200, SQLite quick_check passed with 131 tables and zero provider connections, and an owned test row and artifact survived container stop/start. Missing encryption-key startup was rejected. These are local image results, not a runtime sizing or fleet capacity recommendation.

The generic `backup_crypto.mjs` library encrypts a complete snapshot using Node's built-in AES-256-GCM with a caller-supplied independent 32-byte key, fresh nonce and authenticated canonical metadata. The metadata binds format version, runtime version, image digest, key identifier and plaintext length. Decryption returns plaintext only after tag verification. Wrong keys, mismatched context, malformed framing and tampering fail with a redacted error. This follows the [Node crypto API](https://nodejs.org/docs/latest-v24.x/api/crypto.html).

The library requires Buffer inputs and strictly validated context objects. It buffers at most 64 MiB of plaintext inside the container-facing Node process; do not run it in a Worker or treat that bound as accepted fleet sizing. Larger databases are held until a reviewed streaming implementation or measured sizing decision supports them. Key custody, replay policy and remote checkpoint acknowledgment are caller responsibilities still awaiting integration.

Run `make test-runtime-crypto` with Node 24+ and Python 3 for the owned SQLite fixture. Thirty-nine independent checks cover real SQLite roundtrip, a separate Node decipher, nonce variation, tampering, context/key/version rejection, strict object descriptors and size/framing limits, including actual encryption/decryption of a full 64 MiB payload. The exact helper also passed these checks on Linux/amd64 Node 24.21.0 in a network-disabled test container; its SQLite fixture was pre-created outside that container. This is crypto component evidence, not a remote recovery drill.

The Dockerfile does not yet bundle or invoke this library. Authenticated Worker/container transport, scoped-key streaming, independent encrypted backup and recovery, deployment and physical fleet acceptance remain separate requirements. The image does not yet include the platform lifecycle supervisor or an authenticated management endpoint. Company account/domain pins and private evidence belong in the operations checkout.
