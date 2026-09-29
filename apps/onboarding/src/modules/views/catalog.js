import { esc, badge, riskTone, dispositionTone, options, uniq } from "../util.js";
import { agentId, allCards, enableable, refusal } from "../model.js";

const FILTERS = ["disposition", "category", "agent", "runtime"];

function matches(card, f) {
  if (f.disposition && card.disposition !== f.disposition) return false;
  if (f.category && card.category !== f.category) return false;
  if (f.agent && !(card.agents || []).includes(f.agent)) return false;
  if (f.runtime) {
    const rts = card.runtimes || ["any"];
    if (!rts.includes(f.runtime) && !rts.includes("any")) return false;
  }
  if (f.q) {
    const hay = [card.id, card.name, card.summary, card.kind, card.category, ...(card.agents || []), ...(card.hooks || [])]
      .join(" ").toLowerCase();
    if (!f.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  }
  return true;
}

export function cardHtml(card) {
  const on = enableable(card);
  const repo = card.repo && /^https?:\/\//.test(card.repo)
    ? `<a href="${esc(card.repo)}" target="_blank" rel="noopener noreferrer">${esc(card.repo.replace(/^https?:\/\/(www\.)?/, ""))}</a>`
    : "";
  return `<article class="sg-card ${on ? "" : "is-disabled"}" ${on ? "" : 'aria-disabled="true"'}>
    <header>
      <h4>${esc(card.name || card.id)}</h4>
      ${badge(card.disposition, dispositionTone(card.disposition))}
    </header>
    <div class="sg-card-id"><code>${esc(card.id)}</code> · ${esc(card.category)} · ${esc(card.kind || "")}</div>
    <p>${esc(card.summary || "")}</p>
    ${on ? "" : `<p class="sg-reason" role="note"><strong>Cannot be enabled:</strong> ${esc(card.id)} ${esc(refusal(card))}.</p>`}
    <div class="sg-meta">
      ${badge(`risk ${card.risk || "?"}`, riskTone(card.risk))}
      ${badge(`approval ${card.approval || "?"}`, String(card.approval) === "yes" ? "warn" : "")}
      ${(card.agents || []).map((a) => badge(a, "agent")).join("")}
      ${(card.runtimes || []).map((r) => badge(r, "runtime")).join("")}
    </div>
    ${repo ? `<div class="sg-repo">${repo}</div>` : ""}
  </article>`;
}

function results(data, f) {
  const cards = allCards(data.modules).filter((c) => matches(c, f));
  cards.sort((a, b) => enableable(b) - enableable(a) || a.id.localeCompare(b.id));
  if (!cards.length) return `<p class="sub">No cards match these filters.</p>`;
  return `<div class="sg-grid">${cards.map(cardHtml).join("")}</div>`;
}

export default {
  id: "catalog",
  title: "Catalog",
  initial: () => ({ disposition: "", category: "", agent: "", runtime: "", q: "" }),
  render({ data, state: f }) {
    const cards = allCards(data.modules);
    const agents = (data.modules.agents || []).map(agentId);
    const runtimes = uniq([...(data.modules.adapters || []).map((a) => a.id)]);
    const count = cards.filter((c) => matches(c, f)).length;
    const select = (name, values, all) => `<label class="sg-field"><span>${esc(name)}</span>
      <select data-filter="${name}">${options(values, f[name], all)}</select></label>`;
    return `<section class="sg-panel">
      <h2>Catalog</h2>
      <p class="sub">Every card from <code>catalog/cards/</code> plus G-Stack connectors. <b>hold</b> and <b>refuse</b> cards are shown but cannot be enabled.</p>
      <form class="sg-filters" role="search" onsubmit="return false">
        <label class="sg-field sg-search"><span>Search</span>
          <input type="search" data-filter="q" value="${esc(f.q)}" placeholder="id, name, summary, hook" autocomplete="off" /></label>
        ${select("disposition", uniq(cards.map((c) => c.disposition)), "All dispositions")}
        ${select("category", uniq(cards.map((c) => c.category)), "All categories")}
        ${select("agent", agents, "All agents")}
        ${select("runtime", runtimes, "All runtimes")}
        <button type="button" class="ghost" data-reset ${FILTERS.some((k) => f[k]) || f.q ? "" : "disabled"}>Reset</button>
      </form>
      <p class="sg-count" aria-live="polite" data-count>${count} of ${cards.length} cards</p>
      <div data-results>${results(data, f)}</div>
    </section>`;
  },
  onInput(el, ctx) {
    const key = el.dataset.filter;
    if (!key) return;
    ctx.state[key] = el.value;
    if (key === "q") {
      const view = el.closest(".sg-panel");
      const total = allCards(ctx.data.modules);
      view.querySelector("[data-results]").innerHTML = results(ctx.data, ctx.state);
      view.querySelector("[data-count]").textContent = `${total.filter((c) => matches(c, ctx.state)).length} of ${total.length} cards`;
      view.querySelector("[data-reset]").disabled = !(FILTERS.some((k) => ctx.state[k]) || ctx.state.q);
    } else {
      ctx.rerender();
    }
  },
  onClick(el, ctx) {
    if (el.closest("[data-reset]")) {
      Object.assign(ctx.state, this.initial());
      ctx.rerender();
    }
  },
};
