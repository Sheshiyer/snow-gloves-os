import { esc, badge, riskTone } from "../util.js";
import { allCards, CONNECTOR_CATEGORIES, gstackCard } from "../model.js";
import { cardHtml } from "./catalog.js";

export default {
  id: "connectors",
  title: "Connectors",
  render({ data }) {
    const conns = data.modules.connectors || [];
    const rows = conns.map((c) => {
      const card = gstackCard(c);
      const caps = (c.capabilities || []).map((cap) => `<tr>
          <td><code>${esc(cap.id)}</code></td>
          <td>${badge(cap.risk || "?", riskTone(cap.risk))}</td>
          <td>${String(cap.approval) === "yes" ? badge("needs approval", "warn") : badge("no approval")}</td></tr>`).join("");
      return `<article class="sg-panel">
        <header class="sg-row"><h3><code>${esc(c.id)}</code></h3>
          <span>${badge(c.auth || "no auth")} ${badge(`risk ${card.risk}`, riskTone(card.risk))} ${card.approval === "yes" ? badge("approval yes", "warn") : ""}</span></header>
        <div class="sg-table-wrap"><table class="sg-table">
          <thead><tr><th scope="col">Capability</th><th scope="col">Risk</th><th scope="col">Approval</th></tr></thead>
          <tbody>${caps}</tbody></table></div>
      </article>`;
    }).join("");
    const mcp = (data.modules.cards || []).filter((c) => CONNECTOR_CATEGORIES.includes(c.category));
    return `<section class="sg-panel">
        <h2>Connectors</h2>
        <p class="sub">G-Stack connectors are served by the fabric and gated per capability. High-risk and write capabilities wait for a yes; the founder accepts the approval rule during onboarding.</p>
      </section>
      <div class="sg-stack">${rows}</div>
      <section class="sg-panel">
        <h3>MCP and connector cards</h3>
        <p class="sub">${allCards(data.modules).filter((c) => CONNECTOR_CATEGORIES.includes(c.category)).length} connector options in total, including these catalog cards.</p>
        <div class="sg-grid">${mcp.map(cardHtml).join("")}</div>
      </section>`;
  },
};
