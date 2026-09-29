// Loaders return { modules, tenants, source }. `tenants` is null when tenant data is unavailable (site mode).

function scalar(raw) {
  const s = raw.trim();
  if (s === "" || s === "~" || s === "null") return null;
  if (s === "[]") return [];
  if (s === "{}") return {};
  if (s.length > 1 && s.startsWith("'") && s.endsWith("'")) return s.slice(1, -1).replace(/''/g, "'");
  if (s.length > 1 && s.startsWith('"') && s.endsWith('"')) {
    try { return JSON.parse(s); } catch { return s.slice(1, -1); }
  }
  if (s === "true") return true;
  if (s === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
  return s;
}

const PAIR = /^([A-Za-z0-9_.-]+):(\s.*|)$/;

// Enough YAML for yaml.safe_dump output of enabled.yaml: top-level scalars,
// lists of scalars, lists of flat mappings, and flat nested mappings.
export function parseSimpleYaml(text) {
  const out = {};
  let key = null;
  let item = null;
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const indent = raw.length - raw.trimStart().length;
    if (indent === 0 && !line.startsWith("- ")) {
      const m = line.match(PAIR);
      if (!m) continue;
      key = m[1];
      out[key] = m[2].trim() === "" ? [] : scalar(m[2]);
      item = null;
      continue;
    }
    if (!key) continue;
    if (line.startsWith("- ")) {
      if (!Array.isArray(out[key])) out[key] = [];
      const body = line.slice(2);
      const m = body.match(PAIR);
      if (m) {
        item = { [m[1]]: scalar(m[2]) };
        out[key].push(item);
      } else {
        item = null;
        out[key].push(scalar(body));
      }
      continue;
    }
    const m = line.match(PAIR);
    if (!m) continue;
    if (item) item[m[1]] = scalar(m[2]);
    else {
      if (Array.isArray(out[key]) && out[key].length === 0) out[key] = {};
      if (out[key] && typeof out[key] === "object" && !Array.isArray(out[key])) out[key][m[1]] = scalar(m[2]);
    }
  }
  return out;
}

export function siteLoader(url) {
  return async () => {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`fetch ${url}: HTTP ${res.status}`);
    return { modules: await res.json(), tenants: null, source: url };
  };
}

export function tauriLoader(invoke) {
  return async () => {
    const modules = JSON.parse(await invoke("read_modules"));
    const rows = await invoke("read_tenant_states");
    const tenants = rows.map((row) => {
      let enabledData = null;
      let parseError = "";
      if (row.enabled) {
        try { enabledData = parseSimpleYaml(row.enabled); } catch (e) { parseError = String(e); }
      }
      return { ...row, enabledData, parseError };
    });
    return { modules, tenants, source: "catalog/modules.json" };
  };
}
