import { existsSync, readFileSync, renameSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Static GitHub Pages build of the modules dashboard: catalog and adapters only, no tenant data.
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const modulesPath = fileURLToPath(new URL("../../catalog/modules.json", import.meta.url));

function readModules() {
  try {
    return readFileSync(modulesPath, "utf8");
  } catch (e) {
    throw new Error(`${modulesPath} is missing; run python3 scripts/build_catalog.py first (${e.message})`);
  }
}

function modulesJson() {
  return {
    name: "snowgloves-modules-json",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split("?")[0].endsWith("/modules.json")) {
          res.setHeader("Content-Type", "application/json");
          res.end(readModules());
          return;
        }
        next();
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "modules.json", source: readModules() });
    },
    writeBundle(options) {
      const page = join(options.dir, "site.html");
      if (existsSync(page)) renameSync(page, join(options.dir, "index.html"));
    },
  };
}

export default {
  base: process.env.SITE_BASE || "/snow-gloves-os/",
  clearScreen: false,
  plugins: [modulesJson()],
  server: { port: 5181, strictPort: true, open: "site.html", fs: { allow: [repoRoot] } },
  preview: { port: 5182, strictPort: true },
  build: {
    outDir: "dist-site",
    emptyOutDir: true,
    target: "es2020",
    rollupOptions: { input: { site: fileURLToPath(new URL("site.html", import.meta.url)) } },
  },
};
