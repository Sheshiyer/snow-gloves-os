# Isolated OmniRoute runtime image

Build the pinned published OmniRoute 3.8.50 package and its production dependency set for Linux/amd64:

```sh
docker build --platform linux/amd64 -t snowgloves-runtime:3.8.50 infra/cloudflare-runtime
```

The image runs the package server directly under `tini` as the non-root `node` user. It requires a nonempty `STORAGE_ENCRYPTION_KEY` supplied at runtime and an owned writable `/data` directory. Keep the key independently recoverable; it protects credential fields rather than encrypting the entire SQLite backup. Never put real credentials in build arguments, image layers or source files.

The health check requires HTTP 200 and the literal `ok` response from `/healthz`. This proves service lifecycle only, not authentication, provider availability or inference. No provider connection is bundled.

On 2026-10-05 an isolated Linux/amd64 image build passed with a 6 GiB build VM and bounded 2 GiB npm heap; the earlier 3 GiB build exhausted memory. The resulting image measured 1,225,676,445 bytes. Actual startup returned HTTP 200, SQLite quick_check passed with 131 tables and zero provider connections, and an owned test row and artifact survived container stop/start. Missing encryption-key startup was rejected. These are local image results, not a runtime sizing or fleet capacity recommendation.

This directory supplies the service image only. Authenticated Worker/container transport, scoped-key streaming, independent encrypted backup and recovery, deployment and physical fleet acceptance remain separate requirements. The image does not yet include the platform lifecycle supervisor or an authenticated management endpoint. Company account/domain pins and private evidence belong in the operations checkout.
