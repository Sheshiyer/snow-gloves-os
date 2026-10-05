import { DurableObject } from 'cloudflare:workers';
import type { BackendFetcher, GatewayConfig } from './transport.ts';
import { authorizeGateway, handleGateway, REDACTED_503 } from './transport.ts';
import { ContainerLifecycleManager } from './lifecycle.ts';

export interface SecretEnv {
  SCOPED_KEYS_JSON: string;
  MANAGEMENT_KEY: string;
  BACKEND_API_KEY: string;
  STORAGE_ENCRYPTION_KEY: string;
  SG_BACKUP_KEY: string;
  SG_BACKUP_KEY_ID: string;
  GATEWAY_INITIALIZE_FRESH?: string;
}

export type RuntimeEnv = Cloudflare.Env & SecretEnv;

export class Gateway extends DurableObject<RuntimeEnv> {
  private lifecycleManager = new ContainerLifecycleManager();

  async fetch(request: Request): Promise<Response> {
    const config: GatewayConfig = {
      SCOPED_KEYS_JSON: this.env.SCOPED_KEYS_JSON,
      MANAGEMENT_KEY: this.env.MANAGEMENT_KEY,
      BACKEND_API_KEY: this.env.BACKEND_API_KEY,
      GATEWAY_INSTANCE_ID: this.env.GATEWAY_INSTANCE_ID,
      GATEWAY_START_ALLOWED: this.env.GATEWAY_START_ALLOWED,
      STORAGE_ENCRYPTION_KEY: this.env.STORAGE_ENCRYPTION_KEY,
    };

    const lazyFetcher: BackendFetcher = {
      fetch: async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const port = await this.lifecycleManager.ensureReady(
          this.ctx.container,
          {
            MANAGEMENT_KEY: this.env.MANAGEMENT_KEY,
            BACKEND_API_KEY: this.env.BACKEND_API_KEY,
            STORAGE_ENCRYPTION_KEY: this.env.STORAGE_ENCRYPTION_KEY,
            SG_BACKUP_KEY: this.env.SG_BACKUP_KEY,
            SG_BACKUP_KEY_ID: this.env.SG_BACKUP_KEY_ID,
            GATEWAY_INSTANCE_ID: this.env.GATEWAY_INSTANCE_ID,
            GATEWAY_START_ALLOWED: this.env.GATEWAY_START_ALLOWED,
            ...(this.env.GATEWAY_INITIALIZE_FRESH !== undefined ? { GATEWAY_INITIALIZE_FRESH: this.env.GATEWAY_INITIALIZE_FRESH } : {}),
          },
          init?.signal ?? request.signal
        );
        return port.fetch(input, init);
      },
    };

    return handleGateway(request, config, lazyFetcher);
  }
}

export default {
  async fetch(request: Request, env: RuntimeEnv): Promise<Response> {
    const config: GatewayConfig = {
      SCOPED_KEYS_JSON: env.SCOPED_KEYS_JSON,
      MANAGEMENT_KEY: env.MANAGEMENT_KEY,
      BACKEND_API_KEY: env.BACKEND_API_KEY,
      GATEWAY_INSTANCE_ID: env.GATEWAY_INSTANCE_ID,
      GATEWAY_START_ALLOWED: env.GATEWAY_START_ALLOWED,
      STORAGE_ENCRYPTION_KEY: env.STORAGE_ENCRYPTION_KEY,
    };

    const authResult = await authorizeGateway(request, config);
    if (authResult.response) {
      return authResult.response;
    }

    if (authResult.authorized?.kind === 'models') {
      return handleGateway(request, config, { fetch: async () => { throw new Error('MODELS_HAS_NO_BACKEND'); } });
    }

    if (!env.GATEWAY_INSTANCE_ID || typeof env.GATEWAY_INSTANCE_ID !== 'string') {
      return REDACTED_503();
    }

    const stub = env.GATEWAY.getByName(env.GATEWAY_INSTANCE_ID);
    const headers = new Headers();
    for (const name of ['authorization', 'content-type', 'accept']) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    const forwarded = new Request(request.url, {
      method: request.method, headers, signal: request.signal,
      ...(authResult.authorized?.kind === 'inference' ? { body: JSON.stringify(authResult.authorized.jsonBody) } : {}),
    });
    return stub.fetch(forwarded);
  },
};
