"""Runtime adapters (schema snowgloves.adapter.v1).

An adapter is one folder: adapters/<id>/adapter.yaml. It says where a runtime
keeps skills, MCP config, rules, and plugins, and which tool it uses to ask the
user a question. render_plan() turns a tenant's enabled modules into the files
that runtime expects; write_plan() writes them.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCHEMA = "snowgloves.adapter.v1"
REQUIRED = ("schema", "id", "name", "question_tool", "plan_mode", "paths", "formats", "install")
PATH_KEYS = ("skills", "mcp", "rules", "plugins")
SKILL_FORMATS = ("skill-md", "hermes-skill-md")
MCP_FORMATS = ("json", "opencode-json", "toml", "yaml")
FALLBACK_QUESTION_TOOL = "numbered-list"
BLOCK_START = "<!-- snowgloves:start -->"
BLOCK_END = "<!-- snowgloves:end -->"

SKILL_CATEGORIES = ("skills", "playbook")
MCP_CATEGORIES = ("mcp", "connector")
PLUGIN_CATEGORIES = ("plugin",)


class AdapterError(ValueError):
    pass


def validate(data: dict, folder: str | None = None) -> list[str]:
    problems: list[str] = []
    for key in REQUIRED:
        if key not in data:
            problems.append(f"missing {key}")
    if data.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA}")
    if folder and data.get("id") != folder:
        problems.append(f"id {data.get('id')!r} does not match folder {folder!r}")
    paths = data.get("paths") or {}
    for key in PATH_KEYS:
        if key not in paths:
            problems.append(f"paths.{key} missing (use null if the runtime has none)")
    formats = data.get("formats") or {}
    if formats.get("skill") not in SKILL_FORMATS:
        problems.append(f"formats.skill must be one of {SKILL_FORMATS}")
    if formats.get("mcp") not in MCP_FORMATS:
        problems.append(f"formats.mcp must be one of {MCP_FORMATS}")
    if not isinstance(data.get("install", []), list):
        problems.append("install must be a list")
    verify = data.get("verify", {})
    if verify not in (True, None) and not isinstance(verify, dict):
        problems.append("verify must be true or a mapping of field -> true")
    return problems


def load_adapter(adapters_dir: Path, runtime: str) -> dict:
    path = adapters_dir / runtime / "adapter.yaml"
    if not path.is_file():
        known = ", ".join(sorted(list_adapters(adapters_dir))) or "none"
        raise AdapterError(f"no adapter for runtime {runtime!r} (known: {known})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems = validate(data, runtime)
    if problems:
        raise AdapterError(f"{path}: " + "; ".join(problems))
    return data


def list_adapters(adapters_dir: Path) -> list[str]:
    if not adapters_dir.is_dir():
        return []
    return sorted(p.name for p in adapters_dir.iterdir() if (p / "adapter.yaml").is_file())


def verify_fields(adapter: dict) -> list[str]:
    verify = adapter.get("verify")
    if verify is True:
        return ["*"]
    if isinstance(verify, dict):
        return [key for key, flag in verify.items() if flag]
    return []


def resolve(template: str | None, roots: dict[str, Path]) -> Path | None:
    if not template:
        return None
    text = template
    for key, value in roots.items():
        text = text.replace("{" + key + "}", str(value))
    return Path(text).expanduser()


@dataclass
class Plan:
    runtime: str
    files: dict[Path, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _skill_md(item: dict, body: str, fmt: str, tenant: str) -> str:
    front = {
        "name": item["id"],
        "description": (item.get("summary") or item.get("name") or item["id"]).strip(),
    }
    if fmt == "hermes-skill-md":
        front["metadata"] = {
            "hermes": {"tags": ["snowgloves", item.get("category", "skills")], "tenant": tenant}
        }
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    lines = [
        "---",
        head,
        "---",
        "",
        f"# {item.get('name') or item['id']}",
        "",
        f"Enabled for tenant `{tenant}` by Snow Gloves. Load `connector-gate` before any external call.",
        "",
    ]
    if item.get("repo"):
        lines += [f"Source: {item['repo']}", ""]
    if item.get("agents"):
        lines += ["Agents: " + ", ".join(item["agents"]), ""]
    if body.strip():
        lines += [body.strip(), ""]
    return "\n".join(lines)


def _mcp_entry(item: dict, fmt: str) -> dict:
    spec = item.get("mcp") if isinstance(item.get("mcp"), dict) else None
    if spec:
        entry = dict(spec)
    else:
        where = item.get("repo") or "the card"
        entry = {"command": f"FILL: launch command for {item['id']} (see {where})", "args": []}
    if fmt == "opencode-json":
        command = entry.pop("command", "")
        args = entry.pop("args", []) or []
        if "url" in entry:
            return {"type": "remote", "url": entry["url"], "enabled": True}
        return {"type": "local", "command": [command, *args], "enabled": True}
    return entry


def _set_dotted(target: dict, dotted: str, value: dict) -> None:
    node = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node.setdefault(parts[-1], {}).update(value)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {_toml_value(v)}" for k, v in value.items()) + " }"
    return json.dumps(str(value))


def _toml_tables(key: str, entries: dict[str, dict]) -> str:
    out: list[str] = []
    for name, entry in entries.items():
        bare = re.fullmatch(r"[A-Za-z0-9_-]+", name)
        out.append(f"[{key}.{name if bare else json.dumps(name)}]")
        for k, v in entry.items():
            out.append(f"{k} = {_toml_value(v)}")
        out.append("")
    return "\n".join(out)


def _mcp_file(path: Path, fmt: str, key: str, entries: dict[str, dict], in_sandbox: bool) -> tuple[Path, str, str | None]:
    """Return (path, content, note). Existing files are merged, never clobbered."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    if fmt in ("json", "opencode-json"):
        wrapper: dict = {}
        try:
            data = json.loads(existing) if existing and existing.strip() else {}
        except json.JSONDecodeError:
            _set_dotted(wrapper, key, entries)
            fragment = path.with_name(path.stem + ".snowgloves" + path.suffix)
            return fragment, json.dumps(wrapper, indent=2) + "\n", (
                f"{path} is not plain JSON (comments?); wrote {fragment.name} to merge by hand"
            )
        _set_dotted(wrapper, key, entries)
        for top, value in wrapper.items():
            if isinstance(value, dict) and isinstance(data.get(top), dict):
                _deep_merge(data[top], value)
            else:
                data[top] = value
        note = f"merged {len(entries)} server(s) into existing {path}" if existing else None
        return path, json.dumps(data, indent=2) + "\n", note
    if fmt == "toml":
        present = tomllib.loads(existing).get(key, {}) if existing else {}
        missing = {k: v for k, v in entries.items() if k not in present}
        block = _toml_tables(key, missing)
        if existing:
            content = existing.rstrip("\n") + ("\n\n" + block if block else "\n")
            skipped = sorted(set(entries) - set(missing))
            note = f"appended {len(missing)} table(s) to {path}" + (
                f"; left existing: {', '.join(skipped)}" if skipped else ""
            )
            return path, content, note
        return path, block, None
    # yaml: config files that carry comments and secrets are never rewritten
    body = yaml.safe_dump({key: entries}, sort_keys=False)
    if existing and not in_sandbox:
        fragment = path.with_name(path.stem + ".snowgloves" + path.suffix)
        return fragment, body, f"{path} exists; wrote {fragment.name} to merge by hand"
    if existing:
        data = yaml.safe_load(existing) or {}
        data.setdefault(key, {}).update(entries)
        return path, yaml.safe_dump(data, sort_keys=False), None
    return path, body, None


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _rules_text(tenant: str, agents: list[str], items: list[dict], fmt: str) -> str:
    lines = [
        f"Snow Gloves tenant `{tenant}`.",
        "",
        "Before any external tool call, check `enabled.yaml` in the tenant folder. "
        "An id that is not listed there is off. Hold and refused ids are never enabled by hand.",
        "",
    ]
    if agents:
        lines += ["Agents: " + ", ".join(agents), ""]
    if items:
        lines.append("Enabled modules:")
        lines += [f"- {i['id']} ({i.get('category', '?')}, risk {i.get('risk', '?')})" for i in items]
        lines.append("")
    text = "\n".join(lines)
    if fmt == "mdc":
        return (
            "---\ndescription: Snow Gloves tenant rules (generated; edits are overwritten)\n"
            "globs:\nalwaysApply: true\n---\n\n" + text
        )
    return text


def upsert_block(existing: str | None, body: str) -> str:
    block = f"{BLOCK_START}\n{body.rstrip()}\n{BLOCK_END}\n"
    if not existing:
        return block
    if BLOCK_START in existing and BLOCK_END in existing:
        head, rest = existing.split(BLOCK_START, 1)
        _, tail = rest.split(BLOCK_END, 1)
        return head + block + tail.lstrip("\n")
    return existing.rstrip("\n") + "\n\n" + block


def render_plan(
    adapter: dict,
    items: list[dict],
    agents: list[str],
    tenant: str,
    roots: dict[str, Path],
    card_bodies: dict[str, str] | None = None,
    in_sandbox: bool = False,
) -> Plan:
    """Build every file this runtime needs for the enabled items. Nothing is written."""
    card_bodies = card_bodies or {}
    runtime = adapter["id"]
    plan = Plan(runtime=runtime)
    paths = adapter["paths"]
    formats = adapter["formats"]

    skills_dir = resolve(paths.get("skills"), roots)
    mcp_entries: dict[str, dict] = {}
    plugin_lines: list[str] = []
    for item in items:
        category = item.get("category", "skills")
        if item.get("disposition") == "pointer":
            plan.skipped.append(f"{item['id']}: pointer (reference only, nothing to install)")
            continue
        if item.get("kind") == "g-stack":
            plan.skipped.append(f"{item['id']}: served by the G-Stack connector fabric, nothing to install")
            continue
        if category in SKILL_CATEGORIES:
            if skills_dir is None:
                plan.skipped.append(f"{item['id']}: {runtime} has no skills path")
                continue
            path = skills_dir / item["id"] / "SKILL.md"
            plan.files[path] = _skill_md(item, card_bodies.get(item["id"], ""), formats["skill"], tenant)
        elif category in MCP_CATEGORIES:
            mcp_entries[item["id"]] = _mcp_entry(item, formats["mcp"])
        elif category in PLUGIN_CATEGORIES:
            template = adapter.get("plugin_install")
            if template:
                plugin_lines.append(
                    "- " + template.replace("{id}", item["id"]).replace("{repo}", item.get("repo") or "?")
                )
            else:
                plugin_lines.append(f"- {item['id']}: {runtime} has no plugin install; see {item.get('repo') or 'card'}")
        else:
            plan.skipped.append(f"{item['id']}: category {category!r} has no render rule")

    if mcp_entries:
        mcp_path = resolve(paths.get("mcp"), roots)
        if mcp_path is None:
            plan.skipped.append(f"{', '.join(mcp_entries)}: {runtime} has no MCP path")
        else:
            key = formats.get("mcp_key") or "mcpServers"
            target, content, note = _mcp_file(mcp_path, formats["mcp"], key, mcp_entries, in_sandbox)
            plan.files[target] = content
            if note:
                plan.notes.append(note)
            if "FILL:" in json.dumps(mcp_entries):
                plan.notes.append("some MCP entries say FILL: add the launch command before starting the runtime")

    rules_path = resolve(paths.get("rules"), roots)
    if rules_path is not None:
        fmt = formats.get("rules", "markdown-block")
        text = _rules_text(tenant, agents, items, fmt)
        if fmt == "mdc":
            plan.files[rules_path] = text
        else:
            existing = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else None
            plan.files[rules_path] = upsert_block(existing, text)

    tenant_dir = roots["tenant"]
    if plugin_lines:
        plan.files[tenant_dir / "runtime" / runtime / "plugins.md"] = (
            f"# Plugins for {adapter['name']}\n\nSnow Gloves does not install plugins. Run these yourself:\n\n"
            + "\n".join(plugin_lines)
            + "\n"
        )
    manifest = {
        "schema": "snowgloves.render.v1",
        "runtime": runtime,
        "tenant": tenant,
        "files": sorted(str(p) for p in plan.files),
        "skipped": plan.skipped,
        "verify": verify_fields(adapter),
    }
    plan.files[tenant_dir / "runtime" / runtime / "render.json"] = json.dumps(manifest, indent=2) + "\n"
    fields = verify_fields(adapter)
    if fields:
        plan.notes.append(f"{runtime} adapter fields still marked verify: {', '.join(fields)}")
    return plan


def write_plan(plan: Plan) -> list[Path]:
    written: list[Path] = []
    for path, content in plan.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
