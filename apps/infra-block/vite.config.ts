import { defineConfig } from 'vite';

// The browser talks to its own origin. The projection server stays on loopback.
const proxy = {
  '/api/infra': {
    target: `http://127.0.0.1:${process.env.SNOWGLOVES_COCKPIT_PORT || '18761'}`,
    changeOrigin: true,
  },
};

export default defineConfig({
  server: { proxy },
  preview: { proxy },
});
