import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

const STEPS = ["welcome","doctor","tenant","paperclip","sources","review","done"];
const state = {
  step: 0,
  doctor: null,
  business: "",
  slug: "",
  company_id: "",
  sources: "",
  result: null,
  smokeLog: ""
};

const root = document.getElementById("app");

function header(){
  const dots = STEPS.map((_,i)=>{
    const cls = i<state.step ? "done" : i===state.step ? "active" : "";
    return `<span class="step-dot ${cls}"></span>`;
  }).join("");
  return `<header>
    <div class="brand"><img class="logo" src="/snowgloves-icon-256.png" alt="Snow Gloves OS logo" /><h1>Snow Gloves OS · Onboarding</h1></div>
    <div class="steps">${dots}</div>
  </header>`;
}

function footer(prev=true,next=true,nextLabel="Continue",nextDisabled=false){
  return `<footer>
    <button class="ghost" ${prev?"":"disabled"} data-action="back">Back</button>
    <button ${nextDisabled?"disabled":""} data-action="next">${nextLabel}</button>
  </footer>`;
}

function slugify(s){return s.toLowerCase().trim().replace(/[^a-z0-9]+/g,"-").replace(/(^-|-$)/g,"").slice(0,40);}

const views = {
  welcome: () => `
    <main><div class="card">
      <h2>Welcome to Snow Gloves OS</h2>
      <p class="sub">A reusable Hand-In-Glove operations platform. This wizard will provision a new tenant, verify the local Paperclip + Hermes runtime, and wire your first sources.</p>
      <div class="checks">
        <div class="check"><span class="badge">1</span><div>Run preflight (doctor)</div></div>
        <div class="check"><span class="badge">2</span><div>Create tenant scaffold</div></div>
        <div class="check"><span class="badge">3</span><div>Bind Paperclip company</div></div>
        <div class="check"><span class="badge">4</span><div>Add knowledge sources</div></div>
      </div>
    </div></main>
    ${footer(false,true,"Start →")}`,

  doctor: () => {
    const d = state.doctor;
    const rows = d?.checks?.map(c=>`<div class="check ${c.status}"><span class="badge">${c.status.toUpperCase()}</span><div>${c.label}</div></div>`).join("") || "<div class='check'><span class='badge'>—</span><div>Click <b>Run check</b> to verify your environment.</div></div>";
    const banner = d ? (d.ok ? `<div class="banner ok">System healthy · ${d.passed}/${d.total} checks passed</div>` : `<div class="banner warn">${d.failed} issue(s) found — review below before continuing</div>`) : "";
    return `
    <main><div class="card">
      <h2>Preflight check</h2>
      <p class="sub">Verifies python, paperclipai, ports 3100/4100, config files, and NVIDIA key. Equivalent to <code>make doctor</code>.</p>
      ${banner}
      <div class="checks">${rows}</div>
      <div style="margin-top:18px;display:flex;gap:10px">
        <button class="ghost" data-action="doctor">Run check</button>
      </div>
    </div></main>
    ${footer(true,true,"Continue",!d)}`;
  },

  tenant: () => `
    <main><div class="card">
      <h2>Create tenant</h2>
      <p class="sub">Each tenant is isolated under <code>tenants/&lt;slug&gt;/</code> with its own sources, memory, embeddings, and approvals.</p>
      <label>Business name</label>
      <input id="biz" value="${state.business}" placeholder="Tryambakam Noesis" data-input="business" />
      <label>Tenant slug</label>
      <input id="slug" value="${state.slug}" placeholder="auto-generated from business name" data-input="slug" />
      <div style="margin-top:8px;color:var(--muted);font-size:12px">Lowercase, alphanumeric, hyphens only.</div>
    </div></main>
    ${footer(true,true,"Create tenant",!state.business || !state.slug)}`,

  paperclip: () => `
    <main><div class="card">
      <h2>Bind Paperclip company</h2>
      <p class="sub">Optional. Paste the company UUID from your Paperclip instance running on <code>127.0.0.1:3100</code>. Leave empty to bind later.</p>
      <label>Paperclip company ID (UUID)</label>
      <input id="cid" value="${state.company_id}" placeholder="2f554495-a76c-4d5a-bec8-71be115bce76" data-input="company_id" />
      <div style="margin-top:14px"><span class="tag">Tip</span><span style="color:var(--muted)">Run <code>paperclipai companies list</code> in your terminal to retrieve IDs.</span></div>
    </div></main>
    ${footer(true,true,"Continue")}`,

  sources: () => `
    <main><div class="card">
      <h2>Knowledge sources</h2>
      <p class="sub">Paths to folders or files that should be indexed. One per line. The Librarian will chunk + embed these into your tenant's vector index.</p>
      <label>Source paths</label>
      <textarea id="sources" placeholder="/Users/you/Documents/business/\n/Users/you/wiki/handbook.md" data-input="sources">${state.sources}</textarea>
    </div></main>
    ${footer(true,true,"Continue")}`,

  review: () => `
    <main><div class="card">
      <h2>Review & provision</h2>
      <p class="sub">Confirm and create the tenant. Re-runnable safely — existing tenants are not overwritten.</p>
      <div class="summary">
        <div class="k">Business</div><div class="v">${state.business||"—"}</div>
        <div class="k">Slug</div><div class="v">${state.slug||"—"}</div>
        <div class="k">Paperclip company</div><div class="v">${state.company_id||"(unbound)"}</div>
        <div class="k">Sources</div><div class="v">${(state.sources||"").split("\n").filter(Boolean).length} entries</div>
      </div>
    </div></main>
    ${footer(true,true,"Provision tenant")}`,

  done: () => {
    const r = state.result;
    return `
    <main><div class="card">
      ${r?.ok ? `<div class="banner ok">Tenant <b>${state.slug}</b> created at <code>${r.path}</code></div>` : `<div class="banner err">${r?.error || "Provisioning failed"}</div>`}
      <h2>You're set</h2>
      <p class="sub">You can now run an end-to-end smoke test to verify the routing/bridge loop, or close this window and continue from the CLI.</p>
      <div style="display:flex;gap:10px;margin:14px 0 18px">
        <button data-action="smoke">Run smoke test</button>
        <button class="ghost" data-action="open-repo">Open repo</button>
      </div>
      ${state.smokeLog ? `<pre class="log">${state.smokeLog}</pre>` : ""}
    </div></main>
    <footer>
      <span style="color:var(--muted);font-size:12px">Snow Gloves OS · v0.1.2</span>
      <button data-action="close">Done</button>
    </footer>`;
  }
};

function render(){
  const view = STEPS[state.step];
  root.innerHTML = header() + (views[view] ? views[view]() : "");
}

root.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  if (action === "back") return window.__back();
  if (action === "next") return window.__next();
  if (action === "doctor") return window.__doctor();
  if (action === "smoke") return window.__smoke();
  if (action === "open-repo") return window.__openRepo();
  if (action === "close") return window.__close();
});

root.addEventListener("input", (event) => {
  const el = event.target;
  if (!el?.dataset?.input) return;
  const key = el.dataset.input;
  if (key === "business") return window.__bizInput(el.value);
  state[key] = el.value;
});

window.__back = () => { if(state.step>0){state.step--;render();} };
window.__next = async () => {
  const view = STEPS[state.step];
  if(view==="tenant" && !state.slug && state.business) state.slug = slugify(state.business);
  if(view==="review") return window.__provision();
  state.step = Math.min(state.step+1, STEPS.length-1);
  render();
  if(STEPS[state.step]==="doctor" && !state.doctor) window.__doctor();
};
window.__bizInput = (v)=>{state.business=v; if(!state.slug || state.slug===slugify(state.business.slice(0,-1))) state.slug=slugify(v); document.getElementById("slug").value=state.slug;};

window.__doctor = async ()=>{
  try{
    state.doctor = await invoke("run_doctor");
  }catch(e){ state.doctor = {ok:false,total:0,passed:0,failed:1,checks:[{status:"err",label:String(e)}]}; }
  render();
};

window.__provision = async ()=>{
  try{
    const r = await invoke("create_tenant", {
      slug: state.slug,
      business: state.business,
      companyId: state.company_id || null,
      sources: (state.sources||"").split("\n").map(s=>s.trim()).filter(Boolean)
    });
    state.result = { ok:true, ...r };
  }catch(e){ state.result = {ok:false, error:String(e)}; }
  state.step = STEPS.indexOf("done"); render();
};

window.__smoke = async ()=>{
  state.smokeLog = "$ make smoke\n";
  render();
  const unlisten = await listen("smoke-line", e => {
    state.smokeLog += e.payload + "\n";
    const log = document.querySelector("pre.log");
    if(log){ log.textContent = state.smokeLog; log.scrollTop = log.scrollHeight; }
  });
  try { await invoke("run_smoke"); } finally { unlisten(); }
};

window.__openRepo = ()=> invoke("open_repo");
window.__close   = ()=> invoke("quit_app");

render();


async function checkForUpdates() {
  try {
    const update = await check();
    if (!update) return;
    const banner = document.createElement("div");
    banner.style.cssText = "position:fixed;bottom:14px;right:14px;background:#1a1e2c;border:1px solid #7c5cff;border-radius:10px;padding:12px 14px;color:#e6e9f2;font:13px ui-sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.45);z-index:9999;display:flex;gap:10px;align-items:center;max-width:340px";
    banner.innerHTML = `<div>Update available: <b>v${update.version}</b><div style="color:#8a91a8;font-size:11px;margin-top:2px">${update.body?.split("\n")[0] || "Click install to update."}</div></div><button class="upd-now" style="background:#7c5cff;border:0;color:#fff;border-radius:6px;padding:7px 10px;font-weight:600;cursor:pointer">Install</button>`;
    document.body.appendChild(banner);
    banner.querySelector(".upd-now").addEventListener("click", async () => {
      banner.innerHTML = "Downloading…";
      await update.downloadAndInstall();
      await relaunch();
    });
  } catch (e) {
    console.warn("update check failed:", e);
  }
}

// fire-and-forget after first paint
setTimeout(checkForUpdates, 1500);
