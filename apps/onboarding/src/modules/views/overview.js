import { esc, badge, dispositionTone } from "../util.js";
import { agentId, allCards, enableable } from "../model.js";

const ROWS = [["ceo"], ["cto"], ["chief-of-staff"]];
const W = 820;
const NODE_W = 150;
const NODE_H = 58;
const ROW_H = 96;

function layout(agents) {
  const ids = agents.map(agentId);
  const placed = new Set(ROWS.flat());
  const rows = ROWS.map((r) => r.filter((id) => ids.includes(id)));
  rows.push(ids.filter((id) => !placed.has(id)));
  const pos = {};
  rows.forEach((row, ri) => {
    const gap = W / (row.length + 1);
    row.forEach((id, i) => { pos[id] = { x: gap * (i + 1), y: 20 + ri * ROW_H + NODE_H / 2 }; });
  });
  return { pos, rows, height: 20 + rows.length * ROW_H };
}

function graph(agents, cardsPerAgent) {
  const { pos, rows, height } = layout(agents);
  const byId = Object.fromEntries(agents.map((a) => [agentId(a), a]));
  const edges = [];
  const link = (a, b, dashed = false) => {
    if (!pos[a] || !pos[b]) return;
    edges.push(`<line x1="${pos[a].x}" y1="${pos[a].y + NODE_H / 2}" x2="${pos[b].x}" y2="${pos[b].y - NODE_H / 2}" class="${dashed ? "sg-edge dashed" : "sg-edge"}" />`);
  };
  link("ceo", "cto");
  link("cto", "chief-of-staff");
  for (const id of rows[rows.length - 1]) link("chief-of-staff", id);
  const nodes = Object.entries(pos).map(([id, p]) => {
    const a = byId[id] || {};
    const label = `${id}: ${a.role || ""}. ${a.skill_count ?? 0} hooked skills, ${cardsPerAgent[id] || 0} catalog cards. Open in catalog.`;
    return `<g class="sg-node" tabindex="0" role="button" data-go-agent="${esc(id)}" aria-label="${esc(label)}">
      <rect x="${p.x - NODE_W / 2}" y="${p.y - NODE_H / 2}" width="${NODE_W}" height="${NODE_H}" rx="12" />
      <text x="${p.x}" y="${p.y - 6}" class="sg-node-title">${esc(id)}</text>
      <text x="${p.x}" y="${p.y + 14}" class="sg-node-sub">${esc(a.skill_count ?? 0)} skills · ${esc(cardsPerAgent[id] || 0)} cards</text>
    </g>`;
  });
  return `<svg class="sg-graph" viewBox="0 0 ${W} ${height}" role="group" aria-label="Agent orchestration graph">
    ${edges.join("")}${nodes.join("")}
  </svg>`;
}

export default {
  id: "overview",
  title: "Overview",
  render({ data }) {
    const m = data.modules;
    const cards = allCards(m);
    const counts = m.counts || {};
    const byDisp = counts.by_disposition || {};
    const byCat = counts.by_category || {};
    const cardsPerAgent = {};
    for (const c of cards) for (const a of c.agents || []) cardsPerAgent[a] = (cardsPerAgent[a] || 0) + 1;
    const stat = (n, label, extra = "") => `<div class="sg-stat ${extra}"><div class="n">${esc(n)}</div><div class="l">${esc(label)}</div></div>`;
    const agents = m.agents || [];
    const rows = agents.map((a) => `<tr>
        <th scope="row"><button type="button" class="sg-link" data-go-agent="${esc(agentId(a))}">${esc(agentId(a))}</button></th>
        <td>${esc(a.role || "")}</td><td>${esc(a.layer || "")}</td>
        <td class="num">${esc(a.skill_count ?? 0)}</td><td class="num">${esc(cardsPerAgent[agentId(a)] || 0)}</td>
        <td>${(a.hooks || []).map((h) => badge(h)).join(" ")}</td></tr>`).join("");
    return `
      <section class="sg-panel">
        <h2>Snow Gloves OS modules</h2>
        <p class="sub">Catalog <code>${esc(m.schema || "")}</code> version ${esc(m.version || "?")}. Cards are pointers; nothing is enabled until a tenant's <code>enabled.yaml</code> lists it.</p>
        <div class="sg-stats">
          ${stat(counts.total ?? (m.cards || []).length, "cards")}
          ${stat((m.cards || []).filter(enableable).length, "enableable cards")}
          ${stat(agents.length, "agents")}
          ${stat((m.adapters || []).length, "runtimes")}
          ${stat((m.connectors || []).length, "G-Stack connectors")}
        </div>
        <div class="sg-split">
          <div><h3>By disposition</h3><div class="sg-chips">${Object.entries(byDisp).map(([k, v]) => `<button type="button" class="sg-chip" data-go-disposition="${esc(k)}">${badge(k, dispositionTone(k))} ${esc(v)}</button>`).join("")}</div></div>
          <div><h3>By category</h3><div class="sg-chips">${Object.entries(byCat).map(([k, v]) => `<button type="button" class="sg-chip" data-go-category="${esc(k)}">${badge(k)} ${esc(v)}</button>`).join("")}</div></div>
        </div>
      </section>
      <section class="sg-panel">
        <h3>Agents</h3>
        <p class="sub">CEO and CTO escalate; the Chief of Staff routes skills to the four working agents. Select an agent to see its cards.</p>
        ${graph(agents, cardsPerAgent)}
        <div class="sg-table-wrap"><table class="sg-table">
          <thead><tr><th scope="col">Agent</th><th scope="col">Role</th><th scope="col">Layer</th><th scope="col" class="num">Skills</th><th scope="col" class="num">Cards</th><th scope="col">Hooks</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </section>`;
  },
  onClick(el, ctx) {
    const agent = el.closest("[data-go-agent]")?.dataset.goAgent;
    if (agent) return ctx.go("catalog", { agent });
    const d = el.closest("[data-go-disposition]")?.dataset.goDisposition;
    if (d) return ctx.go("catalog", { disposition: d });
    const c = el.closest("[data-go-category]")?.dataset.goCategory;
    if (c) return ctx.go("catalog", { category: c });
  },
  onKey(ev, ctx) {
    const node = ev.target.closest?.("g[data-go-agent]");
    if (node && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      ctx.go("catalog", { agent: node.dataset.goAgent });
    }
  },
};
