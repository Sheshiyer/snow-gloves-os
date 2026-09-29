import template from "../../../../../prompts/onboard-interview.md?raw";
import { esc, badge, riskTone, dispositionTone, command, copyButton } from "../util.js";
import {
  agentId, allCards, enableable, refusal, needsApproval, runtimeFits, renderPrompt,
  SKILL_CATEGORIES, CONNECTOR_CATEGORIES, PLUGIN_CATEGORIES, FALLBACK_QUESTION_TOOL,
} from "../model.js";

const STEPS = [
  ["runtimes", "Runtimes"],
  ["agents", "Agents"],
  ["skills", "Skills"],
  ["connectors", "Connectors"],
  ["preferences", "Preferences"],
  ["review", "Prompt and commands"],
];

const APPROVAL_MODES = [
  ["always-ask", "Ask before every action"],
  ["ask-on-write", "Ask before anything that writes"],
  ["ask-on-send", "Ask before anything that sends or spends"],
];

const FACTS = [
  ["owner", "Owner", "Who decides, how they decide, and what an agent must never do, even if asked."],
  ["company", "Company", "What the business is and who it serves."],
  ["customer", "Customer", "The problem in the customer's words, the trigger, and the objections."],
  ["offer", "Offer", "What is sold, the price if stated, and promises that have a source."],
  ["voice", "Voice", "One quoted sample that sounds like the owner, the file it came from, and phrases that must never appear."],
  ["proof", "Proof", "Approved claims, each with the file it came from. Leave blank if you are not sure; write \"none\" if there are none."],
];

const SLUG = /^[a-z0-9][a-z0-9-]*$/;
const slugify = (s) => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 40);
const toggle = (list, id, on) => (on ? [...new Set([...list, id])] : list.filter((x) => x !== id));

function initial() {
  return {
    step: 0,
    runtimes: [],
    primary: "",
    agents: [],
    skills: [],
    connectors: [],
    acks: [],
    prefs: { name: "", slug: "", approval_mode: "", render: "", project: "", notes: "" },
    facts: Object.fromEntries(FACTS.map(([k]) => [k, ""])),
    sources: "",
    slugTouched: false,
  };
}

function fill(text) {
  return `<p class="sg-fill" role="note"><strong>FILL:</strong> ${esc(text)}</p>`;
}

function check({ name, value, checked, disabled = false, label, detail = "", extra = "" }) {
  const id = `g-${name}-${value}`;
  return `<label class="sg-option ${disabled ? "is-disabled" : ""}" for="${esc(id)}">
    <input type="checkbox" id="${esc(id)}" data-g="${esc(name)}" value="${esc(value)}" ${checked ? "checked" : ""} ${disabled ? 'disabled aria-disabled="true"' : ""} />
    <span class="sg-option-body"><span class="sg-option-title">${label}</span>${detail ? `<span class="sg-option-detail">${detail}</span>` : ""}${extra}</span>
  </label>`;
}

// ---------------------------------------------------------------- derived

function selectedConnectors(state, byId) {
  return state.connectors.filter((id) => byId[id] && (!needsApproval(byId[id]) || state.acks.includes(id)));
}

function openQuestions(state, byId) {
  const q = [];
  if (!state.prefs.name) q.push("tenant: the business name.");
  if (!state.prefs.slug) q.push("tenant: a slug (lowercase letters, digits, dashes).");
  else if (!SLUG.test(state.prefs.slug)) q.push(`tenant: "${state.prefs.slug}" is not a valid slug; use lowercase letters, digits, and dashes.`);
  if (!state.runtimes.length) q.push("runtimes: which runtime(s) you will run Snow Gloves in.");
  else if (!state.primary) q.push("runtimes: which runtime is primary.");
  if (!state.agents.length) q.push("agents: which Snow Gloves agents this business needs first.");
  if (state.agents.length && !state.skills.length) q.push("skills: the one skill the first job needs, for at least one chosen agent.");
  for (const id of state.connectors) {
    if (byId[id] && needsApproval(byId[id]) && !state.acks.includes(id)) q.push(`connectors: ${id} is ${byId[id].risk} risk; say yes to its approval rule or drop it.`);
  }
  if (!state.prefs.approval_mode) q.push("preferences: approval mode (always-ask, ask-on-write, ask-on-send).");
  if (!state.prefs.render) q.push("preferences: may renders write runtime config, or stay a dry run?");
  if (!state.prefs.project) q.push("preferences: the absolute path of the project where project-scoped rules and MCP files go.");
  for (const [k, title, ask] of FACTS) if (!state.facts[k].trim()) q.push(`${title.toLowerCase()}: ${ask}`);
  if (!state.sources.trim()) q.push("sources: folders or repos the Librarian should ingest (paths only).");
  return q;
}

function harvest(state, byId, questions) {
  const list = (ids, note = () => "") => (ids.length ? ids.map((id) => `- ${id}${note(id)}`).join("\n") : "- none");
  const prose = (key, ask) => state.facts[key].trim() || `FILL: ${ask}`;
  const proof = state.facts.proof.trim();
  const connectors = selectedConnectors(state, byId);
  const pending = state.connectors.filter((id) => !connectors.includes(id)).map((id) => `- FILL: ${id} needs the approval rule accepted`);
  const prefs = [
    state.prefs.approval_mode ? `approval_mode: ${state.prefs.approval_mode}` : "FILL: approval_mode (always-ask, ask-on-write, ask-on-send)",
    state.prefs.render ? `render: ${state.prefs.render}` : "FILL: render (dry-run or write)",
    state.prefs.project ? `project: ${state.prefs.project}` : "FILL: project (absolute path of this project)",
    ...(state.prefs.notes.trim() ? state.prefs.notes.trim().split("\n").map((l) => l.trim()).filter(Boolean) : []),
  ];
  const sources = state.sources.split("\n").map((s) => s.trim()).filter(Boolean);
  const sections = [
    ["Tenant", `slug: ${state.prefs.slug || "FILL: slug"}\nname: ${state.prefs.name || "FILL: business name"}`],
    ...FACTS.filter(([k]) => k !== "proof").map(([k, title, ask]) => [title, prose(k, ask)]),
    ["Proof", !proof ? `FILL: ${FACTS[5][2]}` : proof.toLowerCase() === "none" ? "No approved claims yet." : proof],
    ["Agents", list(state.agents)],
    ["Skills", list(state.skills)],
    ["Connectors", [connectors.length || !pending.length ? list(connectors) : "", ...pending].filter(Boolean).join("\n")],
    ["Runtimes", list(state.runtimes, (id) => (id === state.primary ? ": primary" : ""))],
    ["Preferences", prefs.join("\n")],
    ["Sources", sources.length ? sources.map((s) => `- ${s}`).join("\n") : "- FILL: source paths"],
    ["Open questions", questions.length ? questions.map((q) => `- FILL: ${q}`).join("\n") : "- none"],
  ];
  return sections.map(([h, body]) => `## ${h}\n\n${body}\n`).join("\n");
}

// ---------------------------------------------------------------- steps

function stepRuntimes(ctx) {
  const s = ctx.state;
  const rows = (ctx.data.modules.adapters || []).map((a) => {
    const tool = a.question_tool || FALLBACK_QUESTION_TOOL;
    return check({
      name: "runtimes", value: a.id, checked: s.runtimes.includes(a.id),
      label: `${esc(a.name)} <code class="sg-dim">${esc(a.id)}</code>`,
      detail: `asks with <code>${esc(tool)}</code>${a.plan_mode ? " · has plan mode" : " · no plan mode"}`,
    });
  }).join("");
  const primary = s.runtimes.length
    ? `<fieldset class="sg-fieldset"><legend>Primary runtime</legend><div class="sg-radios">${s.runtimes.map((id) => `
        <label for="g-primary-${esc(id)}"><input type="radio" name="g-primary" id="g-primary-${esc(id)}" data-g="primary" value="${esc(id)}" ${s.primary === id ? "checked" : ""} /> ${esc(id)}</label>`).join("")}</div></fieldset>`
    : fill("pick at least one runtime. More than one is fine; one of them is primary.");
  return `<p class="sub">Interview step 8. Which runtimes will you run Snow Gloves in? The primary one runs the interview prompt.</p>
    <fieldset class="sg-fieldset"><legend>Runtimes</legend><div class="sg-options">${rows}</div></fieldset>${primary}`;
}

function stepAgents(ctx) {
  const s = ctx.state;
  const cards = allCards(ctx.data.modules).filter(enableable);
  const rows = (ctx.data.modules.agents || []).map((a) => {
    const id = agentId(a);
    const n = cards.filter((c) => (c.agents || []).includes(id)).length;
    return check({
      name: "agents", value: id, checked: s.agents.includes(id),
      label: `<code>${esc(id)}</code> ${esc(a.role || "")}`,
      detail: `${n} enableable cards · hooks ${esc((a.hooks || []).join(", ") || "none")}`,
    });
  }).join("");
  return `<p class="sub">Interview step 5. Which agents (rooms) does this business need first? Start small: one room and the skill its first job needs.</p>
    <fieldset class="sg-fieldset"><legend>Agents</legend><div class="sg-options">${rows}</div></fieldset>
    ${s.agents.length ? "" : fill("pick at least one agent. Skills are offered per agent.")}`;
}

function cardOption(c, s, name, extra = "") {
  const fits = runtimeFits(c, s.runtimes);
  const tags = [
    badge(c.disposition, dispositionTone(c.disposition)),
    c.disposition === "pointer" ? badge("reference only", "info") : "",
    CONNECTOR_CATEGORIES.includes(c.category) ? `${badge(`risk ${c.risk}`, riskTone(c.risk))} ${badge(`approval ${c.approval}`, c.approval === "yes" ? "warn" : "")}` : "",
    fits ? "" : badge(`runtimes ${(c.runtimes || []).join(",")}`, "warn"),
  ].join(" ");
  return check({
    name, value: c.id, checked: s[name].includes(c.id),
    label: `<code>${esc(c.id)}</code> ${tags}`,
    detail: esc(c.summary || c.name || ""),
    extra,
  });
}

function blockedList(cards) {
  if (!cards.length) return "";
  return `<details class="sg-blocked"><summary>Not offered (${cards.length}): shown for reference, never enabled</summary>
    <div class="sg-options">${cards.map((c) => check({
      name: "blocked", value: c.id, checked: false, disabled: true,
      label: `<code>${esc(c.id)}</code> ${badge(c.disposition, dispositionTone(c.disposition))}`,
      detail: `${esc(c.id)} ${esc(refusal(c))}.`,
    })).join("")}</div></details>`;
}

function stepSkills(ctx) {
  const s = ctx.state;
  if (!s.agents.length) return `<p class="sub">Interview step 6.</p>${fill("go back and pick at least one agent; skills are filtered to the agents you chose.")}`;
  const cards = allCards(ctx.data.modules).filter((c) => [...SKILL_CATEGORIES, ...PLUGIN_CATEGORIES].includes(c.category));
  const order = (a, b) => (a.disposition !== "add") - (b.disposition !== "add") || a.id.localeCompare(b.id);
  const groups = s.agents.map((agent) => {
    const mine = cards.filter((c) => (c.agents || []).includes(agent));
    const offered = mine.filter(enableable).sort(order);
    return `<fieldset class="sg-fieldset"><legend><code>${esc(agent)}</code> · ${offered.length} offered</legend>
      ${offered.length ? `<div class="sg-options">${offered.map((c) => cardOption(c, s, "skills")).join("")}</div>` : '<p class="sg-dim">No enableable cards for this agent.</p>'}
      ${blockedList(mine.filter((c) => !enableable(c)))}
    </fieldset>`;
  }).join("");
  return `<p class="sub">Interview step 6. For each agent, which skills? <b>add</b> cards come first; <b>pointer</b> cards are reference only. A card flagged with runtimes may not load in the runtimes you picked.</p>
    ${groups}${s.skills.length ? "" : fill("pick the one skill the first job needs.")}`;
}

function stepConnectors(ctx) {
  const s = ctx.state;
  const cards = allCards(ctx.data.modules).filter((c) => CONNECTOR_CATEGORIES.includes(c.category));
  const offered = cards.filter(enableable).sort((a, b) => a.id.localeCompare(b.id));
  const rows = offered.map((c) => {
    if (!(s.connectors.includes(c.id) && needsApproval(c))) return cardOption(c, s, "connectors");
    const id = `g-ack-${c.id}`;
    return `<div class="sg-option-group">${cardOption(c, s, "connectors")}
      <label class="sg-ack" for="${esc(id)}"><input type="checkbox" id="${esc(id)}" data-g="acks" value="${esc(c.id)}" ${s.acks.includes(c.id) ? "checked" : ""} />
        <span>Yes: every ${esc(c.risk)}-risk or write call from <code>${esc(c.id)}</code> waits for my approval.</span></label></div>`;
  }).join("");
  return `<p class="sub">Interview step 7. Which MCP servers or connectors? High-risk and write connectors need you to say yes to the approval rule.</p>
    <fieldset class="sg-fieldset"><legend>Connectors</legend><div class="sg-options">${rows}</div>${blockedList(cards.filter((c) => !enableable(c)))}</fieldset>
    ${s.connectors.filter((id) => !s.acks.includes(id) && needsApproval(offered.find((c) => c.id === id) || {})).map((id) => fill(`${id} needs your yes to its approval rule, or drop it.`)).join("")}`;
}

function stepPreferences(ctx) {
  const p = ctx.state.prefs;
  const radio = (name, value, label) => `<label for="g-${name}-${value}"><input type="radio" name="g-${name}" id="g-${name}-${value}" data-g="${name}" value="${value}" ${p[name] === value ? "checked" : ""} /> ${esc(label)}</label>`;
  return `<p class="sub">Interview steps 1 and 9. Tenant identity and how Snow Gloves should behave.</p>
    <div class="row">
      <label class="sg-field"><span>Business name</span><input id="g-name" data-g-text="prefs.name" value="${esc(p.name)}" placeholder="Acme Studio" /></label>
      <label class="sg-field"><span>Tenant slug</span><input id="g-slug" data-g-text="prefs.slug" value="${esc(p.slug)}" placeholder="acme-studio" pattern="[a-z0-9][a-z0-9-]*" /></label>
    </div>
    <fieldset class="sg-fieldset"><legend>Approval mode</legend><div class="sg-radios">${APPROVAL_MODES.map(([v, l]) => radio("approval_mode", v, `${v}: ${l}`)).join("")}</div></fieldset>
    <fieldset class="sg-fieldset"><legend>Renders</legend><div class="sg-radios">${radio("render", "dry-run", "dry-run: print what would change")}${radio("render", "write", "write: allow writing runtime config")}</div></fieldset>
    <label class="sg-field"><span>Project path (absolute)</span><input id="g-project" data-g-text="prefs.project" value="${esc(p.project)}" placeholder="/Users/you/Projects/acme" /></label>
    <label class="sg-field"><span>Sources, one path per line (step 10)</span><textarea id="g-sources" data-g-text="sources" placeholder="/Users/you/Documents/acme/">${esc(ctx.state.sources)}</textarea></label>
    <label class="sg-field"><span>Anything else to remember (key: value lines)</span><textarea id="g-notes" data-g-text="prefs.notes" placeholder="timezone: Europe/Berlin">${esc(p.notes)}</textarea></label>`;
}

function outputs(ctx) {
  const s = ctx.state;
  const byId = Object.fromEntries(allCards(ctx.data.modules).map((c) => [c.id, c]));
  const questions = openQuestions(s, byId);
  const slug = s.prefs.slug || "<slug>";
  const ids = [...s.agents, ...s.skills, ...selectedConnectors(s, byId)];
  const runtimes = s.primary ? [s.primary, ...s.runtimes.filter((r) => r !== s.primary)] : s.runtimes;
  const draft = harvest(s, byId, questions);
  const prompts = runtimes.map((rt) => {
    const text = renderPrompt(ctx.data.modules, rt, template);
    return `<div class="sg-prompt">
      ${command(`python3 scripts/onboard.py --prompt ${rt}`)}
      <details><summary>Prompt for ${esc(rt)}${rt === s.primary ? " (primary)" : ""} · ${text.length.toLocaleString()} characters</summary>
        <div class="sg-row">${copyButton(text, "Copy prompt")}</div><pre class="log">${esc(text)}</pre></details></div>`;
  }).join("");
  return `
    <h3>Open questions (${questions.length})</h3>
    ${questions.length ? `<div class="sg-fills">${questions.map(fill).join("")}</div>` : '<p class="banner ok">Nothing missing. The interview will still confirm each answer.</p>'}
    <h3>1. Run the interview</h3>
    <p class="sub">Paste the prompt into ${s.primary ? `<b>${esc(s.primary)}</b>` : "your runtime"} inside the project you have been building. It enters plan mode, asks one decision at a time, turns every gap above into a question, and writes <code>snowgloves-harvest.md</code>.</p>
    ${prompts || fill("pick a runtime first; the prompt is rendered per runtime.")}
    <h3>2. Apply the harvest</h3>
    ${command(`python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant ${slug}`)}
    <details><summary>Draft snowgloves-harvest.md from these answers (FILL: lines are not facts)</summary>
      <div class="sg-row">${copyButton(draft, "Copy draft")}</div><pre class="log">${esc(draft)}</pre></details>
    <h3>3. Or enable directly</h3>
    <p class="sub">Writes <code>tenants/${esc(slug)}/enabled.yaml</code> only; the harvest also writes context and runtime preferences.</p>
    ${ids.length ? command(`python3 scripts/onboard.py --enable ${ids.join(",")} --tenant ${slug}`) : fill("pick agents, skills, or connectors to build the --enable command.")}
    <h3>4. Render for each runtime</h3>
    ${runtimes.length ? runtimes.map((rt) => command(`python3 scripts/onboard.py --render-adapter ${rt} --tenant ${slug}${s.prefs.project ? ` --project ${s.prefs.project}` : ""}${s.prefs.render === "write" ? " --write" : ""}`)).join("") : fill("pick a runtime to render.")}`;
}

function stepReview(ctx) {
  const facts = FACTS.map(([k, title, ask]) => `
    <label class="sg-field"><span>${esc(title)}</span>
      <textarea id="g-fact-${k}" data-g-text="facts.${k}" rows="2" placeholder="${esc(ask)}">${esc(ctx.state.facts[k])}</textarea></label>`).join("");
  return `<p class="sub">Interview steps 2 to 4. The interview reads the repo first, so you can leave these blank; anything blank becomes a <b>FILL:</b> question the agent must ask you.</p>
    <details class="sg-facts" ${Object.values(ctx.state.facts).some((v) => v.trim()) ? "open" : ""}><summary>Add context now (optional)</summary>${facts}</details>
    <div data-outputs>${outputs(ctx)}</div>`;
}

const RENDER = { runtimes: stepRuntimes, agents: stepAgents, skills: stepSkills, connectors: stepConnectors, preferences: stepPreferences, review: stepReview };

export default {
  id: "guided",
  title: "Guided onboarding",
  initial,
  render(ctx) {
    const s = ctx.state;
    const [key, title] = STEPS[s.step];
    const nav = STEPS.map(([k, t], i) => `<li><button type="button" class="sg-step ${i < s.step ? "done" : ""}" data-g-step="${i}" ${i === s.step ? 'aria-current="step"' : ""}>${i + 1}. ${esc(t)}</button></li>`).join("");
    return `<section class="sg-panel sg-guided">
      <h2>Guided onboarding</h2>
      <p class="sub">The same steps as <code>prompts/onboard-interview.md</code>. Nothing here writes files; it builds the prompt to paste and the commands to run.</p>
      <ol class="sg-stepper">${nav}</ol>
      <h3>${esc(title)}</h3>
      ${RENDER[key](ctx)}
      <div class="sg-row sg-footer">
        <button type="button" class="ghost" data-g-nav="-1" ${s.step === 0 ? "disabled" : ""}>Back</button>
        ${s.step < STEPS.length - 1 ? `<button type="button" data-g-nav="1">Continue</button>` : `<button type="button" class="ghost" data-g-reset>Start over</button>`}
      </div>
    </section>`;
  },
  onClick(el, ctx) {
    const s = ctx.state;
    const step = el.closest("[data-g-step]");
    if (step) { s.step = Number(step.dataset.gStep); return ctx.rerender({ top: true }); }
    const nav = el.closest("[data-g-nav]");
    if (nav) { s.step = Math.max(0, Math.min(STEPS.length - 1, s.step + Number(nav.dataset.gNav))); return ctx.rerender({ top: true }); }
    if (el.closest("[data-g-reset]")) { Object.assign(s, initial()); return ctx.rerender({ top: true }); }
  },
  onChange(el, ctx) {
    const s = ctx.state;
    const name = el.dataset.g;
    if (!name) return;
    if (name === "primary") s.primary = el.value;
    else if (name === "approval_mode" || name === "render") s.prefs[name] = el.value;
    else if (Array.isArray(s[name])) {
      s[name] = toggle(s[name], el.value, el.checked);
      if (name === "runtimes") {
        if (!s.runtimes.includes(s.primary)) s.primary = s.runtimes[0] || "";
      }
      if (name === "connectors" && !el.checked) s.acks = toggle(s.acks, el.value, false);
    }
    ctx.rerender();
  },
  onInput(el, ctx) {
    const path = el.dataset.gText;
    if (!path) return;
    const s = ctx.state;
    const [a, b] = path.split(".");
    if (b) s[a][b] = el.value; else s[a] = el.value;
    if (path === "prefs.name") {
      if (!s.slugTouched) {
        s.prefs.slug = slugify(el.value);
        const slug = el.closest(".sg-panel").querySelector("#g-slug");
        if (slug) slug.value = s.prefs.slug;
      }
    }
    if (path === "prefs.slug") {
      s.prefs.slug = el.value.trim();
      s.slugTouched = Boolean(s.prefs.slug);
    }
    const out = el.closest(".sg-panel").querySelector("[data-outputs]");
    if (out) out.innerHTML = outputs(ctx);
  },
};
