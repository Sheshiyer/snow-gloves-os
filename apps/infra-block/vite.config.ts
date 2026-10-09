import { defineConfig } from 'vite';
import { fleetProxyOptions } from './src/fleet-proxy.ts';

// The browser talks to its own origin. The projection server stays on loopback.
const proxy = {
  '/api/fleet': fleetProxyOptions(),
  '/api/infra': {
    target: `http://127.0.0.1:${process.env.SNOWGLOVES_COCKPIT_PORT || '18761'}`,
    changeOrigin: true,
  },
};

// Explicit deployment hostnames only; never disable Vite's Host validation.
const allowedHosts = (process.env.SNOWGLOVES_UI_ALLOWED_HOSTS || '')
  .split(',').map((host) => host.trim()).filter(Boolean);

export default defineConfig({
  server: { proxy, allowedHosts },
  preview: { proxy, allowedHosts },
});
