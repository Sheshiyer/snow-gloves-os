import { fileURLToPath } from "node:url";

// The modules dashboard imports prompts/onboard-interview.md from the repo root.
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

export default {
  clearScreen: false,
  server: { port: 5180, strictPort: true, fs: { allow: [repoRoot] } },
  build: { outDir: "dist", emptyOutDir: true, target: "esnext" }
};
