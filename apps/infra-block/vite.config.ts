import { defineConfig } from 'vite';

// The browser talks to its own origin. The projection server stays on loopback.
const proxy = {
  '/api/fleet': {
    target: 'http://127.0.0.1:4101',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api\/fleet/, '/v1'),
  },
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
