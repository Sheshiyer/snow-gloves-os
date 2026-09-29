const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ENTITIES[c]);

export const badge = (text, tone = "") => `<span class="sg-badge ${tone}">${esc(text)}</span>`;

export const riskTone = (risk) => (risk === "high" ? "err" : risk === "medium" ? "warn" : "ok");

export const dispositionTone = (d) =>
  ({ add: "ok", pointer: "info", hold: "warn", refuse: "err" })[d] || "";

export function copyButton(text, label = "Copy") {
  return `<button type="button" class="ghost sg-copy" data-copy="${esc(text)}" aria-label="${esc(label)}: ${esc(text.slice(0, 80))}">${esc(label)}</button>`;
}

export function command(text) {
  return `<div class="sg-cmd"><code>${esc(text)}</code>${copyButton(text)}</div>`;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

export function options(values, selected, allLabel) {
  const rows = [`<option value="">${esc(allLabel)}</option>`];
  for (const v of values) {
    const [value, label] = Array.isArray(v) ? v : [v, v];
    rows.push(`<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(label)}</option>`);
  }
  return rows.join("");
}

export const uniq = (list) => [...new Set(list)].sort();
