// Mirrors the enable rules and prompt rendering in scripts/onboard.py. The CLI stays authoritative.

export const ENABLEABLE = ["add", "pointer"];
export const FALLBACK_QUESTION_TOOL = "numbered-list";
export const SKILL_CATEGORIES = ["skills", "playbook"];
export const CONNECTOR_CATEGORIES = ["mcp", "connector"];
export const PLUGIN_CATEGORIES = ["plugin"];

export const REFUSAL = {
  hold: "is on hold: it is listed in the catalog but waits on a founder pick and a review before it can be enabled",
  refuse: "is refused: the catalog reviewed it and decided Snow Gloves will not run it",
};

export const enableable = (card) => card.enableable !== false && ENABLEABLE.includes(card.disposition);

export const refusal = (card) =>
  REFUSAL[card.disposition] || `has disposition '${card.disposition}' and cannot be enabled`;

export const agentId = (agent) => agent.slug || agent.id;

export function gstackCard(conn) {
  const caps = (conn.capabilities || []).filter((c) => c && typeof c === "object");
  const risks = caps.map((c) => c.risk || "low");
  const risk = risks.includes("high") ? "high" : risks.includes("medium") ? "medium" : "low";
  const ids = caps.map((c) => c.id || "?").join(", ");
  return {
    category: "connector",
    kind: "g-stack",
    disposition: "add",
    risk,
    approval: caps.some((c) => ["yes", "true"].includes(String(c.approval).toLowerCase())) ? "yes" : "no",
    summary: ids ? `G-Stack connector (${conn.auth || "no auth"}): ${ids}` : "G-Stack connector",
    ...conn,
  };
}

export function allCards(modules) {
  const rows = (modules.cards || []).filter((c) => c && c.id);
  const seen = new Set(rows.map((c) => c.id));
  for (const conn of modules.connectors || []) {
    if (conn?.id && !seen.has(conn.id)) {
      rows.push(gstackCard(conn));
      seen.add(conn.id);
    }
  }
  return rows;
}

export function verifyFields(adapter) {
  const v = adapter.verify;
  if (v === true) return ["*"];
  if (v && typeof v === "object") return Object.entries(v).filter(([, flag]) => flag).map(([k]) => k);
  return [];
}

export const needsApproval = (card) => card.risk === "high" || String(card.approval).toLowerCase() === "yes";

export function runtimeFits(card, runtimes) {
  const rts = card.runtimes || ["any"];
  return !runtimes.length || rts.includes("any") || rts.some((r) => runtimes.includes(r));
}

function optionLines(modules) {
  const out = ["### Agents (rooms)", ""];
  for (const a of modules.agents || []) {
    const role = a.role || a.name || "";
    out.push(`- \`${agentId(a)}\`` + (role ? ` — ${role}` : ""));
  }
  const cards = allCards(modules);
  const offered = cards.filter(enableable);
  const groups = [
    ["Skills", SKILL_CATEGORIES],
    ["Connectors", CONNECTOR_CATEGORIES],
    ["Plugins", PLUGIN_CATEGORIES],
  ];
  const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  for (const [title, cats] of groups) {
    const rows = offered.filter((c) => cats.includes(c.category));
    out.push("", `### ${title}`, "");
    if (!rows.length) {
      out.push("- none offered yet");
      continue;
    }
    rows.sort((a, b) => (a.disposition !== "add") - (b.disposition !== "add") || byId(a, b));
    for (const c of rows) {
      const bits = [c.disposition || ""];
      if (c.agents?.length) bits.push("agents " + c.agents.join(","));
      if (cats[0] !== "skills") bits.push(`risk ${c.risk || "?"}, approval ${c.approval || "?"}`);
      if (c.runtimes?.length) bits.push("runtimes " + c.runtimes.join(","));
      out.push(`- \`${c.id}\` — ${c.summary || c.name || ""} (${bits.join("; ")})`);
    }
  }
  out.push("", "### Runtimes", "");
  for (const rt of modules.adapters || []) out.push(`- \`${rt.id}\` — ${rt.name} (asks with ${rt.question_tool})`);
  const blocked = cards.filter((c) => !enableable(c)).sort(byId);
  if (blocked.length) {
    out.push("", "### Not offered (explain, never enable)", "");
    for (const c of blocked) out.push(`- \`${c.id}\` — ${c.disposition}`);
  }
  return out.join("\n");
}

export function renderPrompt(modules, runtime, template) {
  const adapter = (modules.adapters || []).find((a) => a.id === runtime);
  if (!adapter) return "";
  const tool = adapter.question_tool || FALLBACK_QUESTION_TOOL;
  const hint =
    tool === FALLBACK_QUESTION_TOOL
      ? "This runtime has no structured question tool, so use the numbered list described below."
      : "Pass the options as the tool's choices, and allow multi-select where the step says so.";
  const plan =
    adapter.plan_mode ||
    "This runtime has no plan mode. Behave as if it were on: read and ask, write nothing until the end.";
  let status = `Built catalog: \`catalog/modules.json\`, version ${modules.version || "?"}, ${allCards(modules).length} cards.`;
  const fields = verifyFields(adapter);
  if (fields.length) {
    status += ` The ${runtime} adapter has unconfirmed fields (${fields.join(", ")}); if the question tool or plan mode does not exist here, fall back to a numbered list and plain turns.`;
  }
  const values = {
    runtime,
    runtime_name: adapter.name,
    question_tool: tool,
    question_hint: hint,
    plan_mode: plan,
    catalog_status: status,
    options: optionLines(modules),
  };
  let text = template;
  for (const [k, v] of Object.entries(values)) text = text.split(`{{${k}}}`).join(v);
  return text;
}
