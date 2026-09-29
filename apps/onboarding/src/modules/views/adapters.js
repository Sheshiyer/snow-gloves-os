import { esc, badge, command } from "../util.js";
import { verifyFields, FALLBACK_QUESTION_TOOL } from "../model.js";

function adapterHtml(a) {
  const unverified = verifyFields(a);
  const tool = a.question_tool || FALLBACK_QUESTION_TOOL;
  const flag = (field) => (unverified.includes(field) || unverified.includes("*") ? ` ${badge("unverified", "warn")}` : "");
  const paths = Object.entries(a.paths || {}).map(([k, v]) =>
    `<div class="k">${esc(k)}</div><div class="v">${v ? `<code>${esc(v)}</code>` : '<span class="sg-dim">none</span>'}${flag(`paths.${k}`)}</div>`).join("");
  const install = (a.install || []).map((line, i) => `<li><code>${esc(line)}</code>${flag(`install.${i}`)}</li>`).join("");
  return `<article class="sg-panel sg-adapter">
    <header class="sg-row">
      <h3>${esc(a.name)} <code class="sg-dim">${esc(a.id)}</code></h3>
      ${unverified.length ? badge(`${unverified.length} unverified`, "warn") : badge("verified", "ok")}
    </header>
    <div class="summary">
      <div class="k">Question tool</div><div class="v"><code>${esc(tool)}</code>${tool === FALLBACK_QUESTION_TOOL ? ` ${badge("numbered list")}` : ""}${flag("question_tool")}</div>
      <div class="k">Plan mode</div><div class="v">${a.plan_mode ? esc(a.plan_mode) : '<span class="sg-dim">none: the prompt tells the agent to act as if plan mode were on</span>'}${flag("plan_mode")}</div>
      ${paths}
      ${a.plugin_install ? `<div class="k">Plugin install</div><div class="v"><code>${esc(a.plugin_install)}</code>${flag("plugin_install")}</div>` : ""}
      ${a.homepage ? `<div class="k">Docs</div><div class="v"><a href="${esc(a.homepage)}" target="_blank" rel="noopener noreferrer">${esc(a.homepage)}</a>${flag("homepage")}</div>` : ""}
    </div>
    ${install ? `<details><summary>Install commands</summary><ul class="sg-list">${install}</ul></details>` : ""}
    ${a.notes ? `<p class="sg-note">${esc(a.notes)}</p>` : ""}
    ${unverified.length ? `<p class="sg-note">Unconfirmed against current ${esc(a.name)} docs: ${unverified.map((f) => `<code>${esc(f)}</code>`).join(", ")}.</p>` : ""}
    <h4>Onboarding prompt</h4>
    ${command(`python3 scripts/onboard.py --prompt ${a.id}`)}
  </article>`;
}

export default {
  id: "adapters",
  title: "Adapters",
  render({ data }) {
    const list = data.modules.adapters || [];
    return `<section class="sg-panel">
        <h2>Runtime adapters</h2>
        <p class="sub">One <code>snowgloves.adapter.v1</code> file per runtime under <code>adapters/</code>. <code>{project}</code> and <code>{home}</code> are filled in at render time.</p>
      </section>
      <div class="sg-stack">${list.map(adapterHtml).join("")}</div>`;
  },
};
