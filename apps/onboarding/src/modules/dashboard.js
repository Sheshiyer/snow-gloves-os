import "./dashboard.css";
import { esc, copyText } from "./util.js";
import overview from "./views/overview.js";
import catalog from "./views/catalog.js";
import adapters from "./views/adapters.js";
import connectors from "./views/connectors.js";
import tenant from "./views/tenant.js";
import guided from "./views/guided.js";

export { siteLoader, tauriLoader } from "./data.js";

const VIEWS = [overview, catalog, adapters, connectors, guided, tenant];

/**
 * Mount the modules dashboard into `el`.
 * @param {HTMLElement} el
 * @param {{ load: () => Promise<{modules: object, tenants: object[]|null}>, mode: "tauri"|"site", hash?: boolean }} opts
 */
export function mountDashboard(el, { load, mode, hash = false }) {
  const views = VIEWS.filter((v) => !v.tauriOnly || mode === "tauri");
  const states = Object.fromEntries(views.map((v) => [v.id, v.initial ? v.initial() : {}]));
  let current = views[0].id;
  let data = null;
  let error = "";

  if (hash) {
    const want = location.hash.replace(/^#\/?/, "");
    if (views.some((v) => v.id === want)) current = want;
  }

  const view = () => views.find((v) => v.id === current);
  const ctx = () => ({
    data,
    mode,
    state: states[current],
    rerender,
    go(tab, patch = {}) {
      if (!views.some((v) => v.id === tab)) return;
      current = tab;
      if (tab === "catalog") Object.assign(states.catalog, catalog.initial(), patch);
      else Object.assign(states[tab], patch);
      if (hash) history.replaceState(null, "", `#/${tab}`);
      rerender({ top: true });
    },
  });

  function tabs() {
    return `<nav class="sg-tabs" aria-label="Dashboard sections"><ul role="tablist">${views.map((v) => `
      <li role="presentation"><button type="button" role="tab" id="sg-tab-${v.id}" aria-controls="sg-view" aria-selected="${v.id === current}" tabindex="${v.id === current ? 0 : -1}" data-sg-tab="${v.id}">${esc(v.title)}</button></li>`).join("")}
    </ul></nav>`;
  }

  function body() {
    if (error) {
      return `<section class="sg-panel"><div class="banner err" role="alert">Could not load the catalog: ${esc(error)}</div>
        <p class="sub">Build it with <code>python3 scripts/build_catalog.py</code>, then reload.</p>
        <button type="button" data-sg-reload>Reload</button></section>`;
    }
    if (!data) return `<section class="sg-panel" aria-busy="true"><p class="sub">Loading catalog…</p></section>`;
    return view().render(ctx());
  }

  function rerender({ top = false } = {}) {
    const focusId = document.activeElement?.id;
    const scroller = el.closest("main") || document.scrollingElement;
    const scroll = scroller?.scrollTop ?? 0;
    el.innerHTML = `${tabs()}<div id="sg-view" class="sg-view" role="tabpanel" aria-labelledby="sg-tab-${current}">${body()}</div>`;
    if (scroller) scroller.scrollTop = top ? 0 : scroll;
    if (focusId) document.getElementById(focusId)?.focus({ preventScroll: true });
  }

  async function reload() {
    error = "";
    data = null;
    rerender();
    try { data = await load(); } catch (e) { error = e?.message || String(e); }
    rerender();
  }

  el.addEventListener("click", async (ev) => {
    const t = ev.target;
    const copy = t.closest("[data-copy]");
    if (copy) {
      const ok = await copyText(copy.dataset.copy);
      const label = copy.textContent;
      copy.textContent = ok ? "Copied" : "Copy failed";
      setTimeout(() => { copy.textContent = label; }, 1200);
      return;
    }
    const tab = t.closest("[data-sg-tab]");
    if (tab) return ctx().go(tab.dataset.sgTab);
    if (t.closest("[data-sg-reload]")) return reload();
    if (data) view().onClick?.(t, ctx());
  });

  el.addEventListener("keydown", (ev) => {
    const tab = ev.target.closest?.("[data-sg-tab]");
    if (tab && (ev.key === "ArrowRight" || ev.key === "ArrowLeft")) {
      const i = views.findIndex((v) => v.id === tab.dataset.sgTab);
      const next = views[(i + (ev.key === "ArrowRight" ? 1 : views.length - 1)) % views.length];
      ctx().go(next.id);
      document.getElementById(`sg-tab-${next.id}`)?.focus();
      return;
    }
    if (data) view().onKey?.(ev, ctx());
  });

  el.addEventListener("input", (ev) => { if (data) view().onInput?.(ev.target, ctx()); });
  el.addEventListener("change", (ev) => {
    if (!data || ev.target.matches("input[type=text], input[type=search], input:not([type]), textarea")) return;
    view().onChange?.(ev.target, ctx());
  });

  if (hash) {
    window.addEventListener("hashchange", () => {
      const want = location.hash.replace(/^#\/?/, "");
      if (want !== current && views.some((v) => v.id === want)) ctx().go(want);
    });
  }

  reload();
  return { reload };
}
