import { esc, badge, riskTone, dispositionTone, command } from "../util.js";
import { allCards, enableable, refusal } from "../model.js";

function tenantHtml(t, byId) {
  const e = t.enabledData;
  const cmds = `${command(`python3 scripts/onboard.py --prompt <runtime>`)}
    ${command(`python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant ${t.slug}`)}`;
  if (!t.enabled) {
    return `<article class="sg-panel">
      <header class="sg-row"><h3>${esc(t.slug)}</h3>${badge("not onboarded", "warn")}</header>
      <p class="sub">No <code>enabled.yaml</code> yet in <code>${esc(t.path)}</code>. Run the interview, then apply the harvest:</p>
      ${cmds}
    </article>`;
  }
  if (!e) {
    return `<article class="sg-panel">
      <header class="sg-row"><h3>${esc(t.slug)}</h3>${badge("unreadable", "err")}</header>
      <p class="sub">Could not parse <code>enabled.yaml</code>: ${esc(t.parseError)}</p>
      <pre class="log">${esc(t.enabled)}</pre></article>`;
  }
  const modules = Array.isArray(e.modules) ? e.modules : [];
  const agents = Array.isArray(e.agents) ? e.agents : [];
  const rows = modules.map((m) => {
    const card = byId[m.id];
    const drift = !card
      ? badge("not in catalog", "err")
      : !enableable(card)
        ? `${badge(`now ${card.disposition}`, "err")} <span class="sg-dim">${esc(card.id)} ${esc(refusal(card))}</span>`
        : "";
    return `<tr>
      <td><code>${esc(m.id)}</code></td><td>${esc(m.category || "")}</td>
      <td>${badge(m.disposition || "?", dispositionTone(m.disposition))}</td>
      <td>${badge(m.risk || "?", riskTone(m.risk))}</td><td>${esc(m.approval ?? "")}</td><td>${drift}</td></tr>`;
  }).join("");
  return `<article class="sg-panel">
    <header class="sg-row"><h3>${esc(t.slug)}</h3>
      <span>${badge(e.schema || "no schema", e.schema === "snowgloves.enabled.v1" ? "ok" : "warn")} ${e.updated_at ? badge(`updated ${e.updated_at}`) : ""}</span></header>
    <p class="sub"><code>${esc(t.path)}/enabled.yaml</code></p>
    <h4>Agents</h4>
    <div class="sg-meta">${agents.length ? agents.map((a) => badge(a, "agent")).join("") : '<span class="sg-dim">none</span>'}</div>
    <h4>Modules (${modules.length})</h4>
    ${modules.length ? `<div class="sg-table-wrap"><table class="sg-table">
      <thead><tr><th scope="col">Id</th><th scope="col">Category</th><th scope="col">Disposition</th><th scope="col">Risk</th><th scope="col">Approval</th><th scope="col">Catalog check</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : '<p class="sg-dim">No modules enabled.</p>'}
    ${t.runtime ? `<details><summary>runtime.yaml</summary><pre class="log">${esc(t.runtime)}</pre></details>` : ""}
    <h4>Adjust</h4>
    ${command(`python3 scripts/onboard.py --enable <id,id> --tenant ${t.slug}`)}
    ${command(`python3 scripts/onboard.py --render-adapter <runtime> --tenant ${t.slug}`)}
  </article>`;
}

export default {
  id: "tenant",
  title: "Tenants",
  tauriOnly: true,
  render({ data }) {
    const tenants = data.tenants || [];
    const byId = Object.fromEntries(allCards(data.modules).map((c) => [c.id, c]));
    return `<section class="sg-panel">
        <h2>Tenants</h2>
        <p class="sub">Enabled state read from <code>tenants/*/enabled.yaml</code> on this machine. Entries whose catalog card is now on hold or refused are flagged.</p>
      </section>
      ${tenants.length ? `<div class="sg-stack">${tenants.map((t) => tenantHtml(t, byId)).join("")}</div>`
        : '<section class="sg-panel"><p class="sub">No tenants under <code>tenants/</code>.</p></section>'}`;
  },
};
