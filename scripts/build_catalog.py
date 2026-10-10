#!/usr/bin/env python3
"""Generate catalog/registry.yaml and catalog/modules.json.

Inputs: catalog/cards/*.md, agents/*/MANIFEST.yaml, skills/registry.yaml,
workflows/skill-hooks.yaml, adapters/*/adapter.yaml, connectors/g-stack/capabilities.yaml.

    python3 scripts/build_catalog.py            # write
    python3 scripts/build_catalog.py --check    # exit 1 if the generated files are stale
    python3 scripts/build_catalog.py --root DIR # operate on another checkout (tests)

Output is deterministic: sorted, no timestamps. Exit 2 on an invalid card.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

SCHEMA = "snowgloves.modules.v1"
ROOT = Path(__file__).resolve().parents[1]

CATEGORIES = ("skills", "mcp", "connector", "plugin", "playbook", "mod")
DISPOSITIONS = ("add", "hold", "refuse", "pointer")
ENABLEABLE = ("add", "pointer")
RISKS = ("low", "medium", "high")
RUNTIMES = ("any", "hermes", "claude", "codex", "cursor", "opencode", "grok", "openclaw", "muse")
REQUIRED = ("id", "name", "category", "kind", "disposition", "repo", "source",
            "risk", "approval", "agents", "runtimes", "summary")
CARD_KEYS = REQUIRED[:10] + ("agents", "hooks", "runtimes", "summary", "mcp")  # mcp is optional


class CatalogError(Exception):
    pass


def _yes_no(value, where: str) -> str:
    if value is True or value == "yes":
        return "yes"
    if value is False or value == "no":
        return "no"
    raise CatalogError(f"{where}: approval must be yes|no, got {value!r}")


def _mcp_problems(mcp) -> list[str]:
    """Optional `mcp:` launch spec: {command|url, args?, env?}. env values are variable names."""
    if not isinstance(mcp, dict):
        return ["mcp must be a mapping with a command or url"]
    out: list[str] = []
    command, url = mcp.get("command"), mcp.get("url")
    if not (isinstance(command, str) and command) and not (isinstance(url, str) and url):
        out.append("mcp needs a string command or url")
    if "args" in mcp and (not isinstance(mcp["args"], list) or not all(isinstance(a, str) for a in mcp["args"])):
        out.append("mcp.args must be a list of strings")
    env = mcp.get("env")
    if "env" in mcp and (not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
        out.append("mcp.env must be a mapping of string -> string (variable names such as ${VAR}, never values)")
    return out


def _load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def split_front_matter(text: str, where: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise CatalogError(f"{where}: missing front matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise CatalogError(f"{where}: unterminated front matter")
    meta = yaml.safe_load(text[4:end]) or {}
    if not isinstance(meta, dict):
        raise CatalogError(f"{where}: front matter is not a mapping")
    return meta, text[end + 5:].strip() + "\n"


def load_agents(root: Path) -> list[dict]:
    registry_path = root / "skills" / "registry.yaml"
    registry = _load_yaml(registry_path) if registry_path.exists() else {}
    skill_lists = (registry or {}).get("agents") or {}
    hooks_path = root / "workflows" / "skill-hooks.yaml"
    routing = ((_load_yaml(hooks_path) or {}).get("routing") or {}) if hooks_path.exists() else {}

    agents = []
    for manifest in sorted((root / "agents").glob("*/MANIFEST.yaml")):
        data = _load_yaml(manifest) or {}
        slug = data.get("slug") or manifest.parent.name
        own = data.get("skills") or []
        skills = skill_lists.get(slug) or own
        agents.append({
            "slug": slug,
            "role": data.get("role", ""),
            "layer": data.get("layer", ""),
            "skill_count": len(skills),
            "hooks": sorted(h["id"] for h in (routing.get(slug) or {}).get("hooks") or [] if "id" in h),
        })
    return sorted(agents, key=lambda a: a["slug"])


def load_cards(root: Path, agents: list[dict]) -> list[dict]:
    agent_slugs = {a["slug"] for a in agents}
    hook_ids = {f"{a['slug']}.{h}" for a in agents for h in a["hooks"]}
    cards = []
    seen: set[str] = set()
    for path in sorted((root / "catalog" / "cards").glob("*.md")):
        where = str(path.relative_to(root))
        meta, body = split_front_matter(path.read_text(encoding="utf-8"), where)
        for key in REQUIRED:
            if key not in meta:
                raise CatalogError(f"{where}: missing {key}")
        cid = str(meta["id"])
        if cid != path.stem:
            raise CatalogError(f"{where}: id {cid!r} does not match file name")
        if cid in seen:
            raise CatalogError(f"{where}: duplicate id {cid}")
        seen.add(cid)
        if meta["category"] not in CATEGORIES:
            raise CatalogError(f"{where}: category must be one of {CATEGORIES}")
        if meta["disposition"] not in DISPOSITIONS:
            raise CatalogError(f"{where}: disposition must be one of {DISPOSITIONS}")
        if meta["risk"] not in RISKS:
            raise CatalogError(f"{where}: risk must be one of {RISKS}")
        agents_list = [str(a) for a in meta.get("agents") or []]
        unknown = sorted(set(agents_list) - agent_slugs)
        if unknown:
            raise CatalogError(f"{where}: unknown agents {unknown}")
        hooks = [str(h) for h in meta.get("hooks") or []]
        missing = sorted(set(hooks) - hook_ids)
        if missing:
            raise CatalogError(f"{where}: unknown hooks {missing}")
        runtimes = [str(r) for r in meta.get("runtimes") or []]
        bad = sorted(set(runtimes) - set(RUNTIMES))
        if bad or not runtimes:
            raise CatalogError(f"{where}: runtimes must be a non-empty subset of {RUNTIMES}")
        mcp = meta.get("mcp")
        if mcp is not None:
            problems = _mcp_problems(mcp)
            if problems:
                raise CatalogError(f"{where}: " + "; ".join(problems))
        card = {
            "id": cid,
            "name": str(meta["name"]),
            "category": meta["category"],
            "kind": str(meta["kind"]),
            "disposition": meta["disposition"],
            "repo": str(meta["repo"] or ""),
            "source": str(meta["source"]),
            "risk": meta["risk"],
            "approval": _yes_no(meta["approval"], where),
            "agents": sorted(agents_list),
            "hooks": sorted(hooks),
            "runtimes": sorted(runtimes),
            "summary": str(meta["summary"]).strip(),
            "enableable": meta["disposition"] in ENABLEABLE,
            "body": body,
        }
        if mcp is not None:
            card["mcp"] = mcp  # passthrough; only present when the card declares it
        cards.append(card)
    return cards


def load_adapters(root: Path) -> list[dict]:
    base = root / "adapters"
    if not base.is_dir():
        return []
    adapters = []
    for path in sorted(base.glob("*/adapter.yaml")):
        data = _load_yaml(path) or {}
        if not isinstance(data, dict):
            raise CatalogError(f"{path.relative_to(root)}: not a mapping")
        data.setdefault("id", path.parent.name)
        adapters.append(data)
    return sorted(adapters, key=lambda a: str(a["id"]))


def load_connectors(root: Path) -> list[dict]:
    path = root / "connectors" / "g-stack" / "capabilities.yaml"
    if not path.exists():
        return []
    data = (_load_yaml(path) or {}).get("connectors") or {}
    out = []
    for cid in sorted(data):
        spec = data[cid] or {}
        caps = []
        for cap in spec.get("capabilities") or []:
            caps.append({
                "id": cap["id"],
                "risk": cap.get("risk", "low"),
                "approval": "yes" if cap.get("approval") in ("required", "yes", True) else "no",
            })
        out.append({
            "id": cid,
            "auth": spec.get("auth", ""),
            "capabilities": sorted(caps, key=lambda c: c["id"]),
        })
    return out


def read_version(root: Path) -> str:
    path = root / "VERSION"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return "0.0.0"


def counts(cards: list[dict]) -> dict:
    by_disp = {d: 0 for d in DISPOSITIONS}
    by_cat = {c: 0 for c in CATEGORIES}
    for card in cards:
        by_disp[card["disposition"]] += 1
        by_cat[card["category"]] += 1
    return {"total": len(cards), "by_disposition": by_disp, "by_category": by_cat}


def build(root: Path) -> dict:
    agents = load_agents(root)
    cards = load_cards(root, agents)
    return {
        "schema": SCHEMA,
        "version": read_version(root),
        "counts": counts(cards),
        "agents": agents,
        "cards": cards,
        "adapters": load_adapters(root),
        "connectors": load_connectors(root),
    }


def render_json(modules: dict) -> str:
    return json.dumps(modules, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_registry(modules: dict) -> str:
    rows = [{k: card[k] for k in CARD_KEYS if k in card} | {"enableable": card["enableable"]} for card in modules["cards"]]
    doc = {
        "schema": modules["schema"],
        "version": modules["version"],
        "counts": modules["counts"],
        "cards": rows,
    }
    header = (
        "# Generated by scripts/build_catalog.py from catalog/cards/*.md. Do not edit.\n"
        "# Cards are pointers. Nothing here is enabled; see tenants/<slug>/enabled.yaml.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=4096)


def outputs(root: Path) -> dict[Path, str]:
    modules = build(root)
    catalog = root / "catalog"
    return {
        catalog / "registry.yaml": render_registry(modules),
        catalog / "modules.json": render_json(modules),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if generated files are stale")
    parser.add_argument("--root", type=Path, default=ROOT, help="repo root (default: this checkout)")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        files = outputs(root)
    except CatalogError as exc:
        print(f"build_catalog: {exc}", file=sys.stderr)
        return 2

    stale = [p for p, text in files.items()
             if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        if stale:
            for p in stale:
                print(f"stale: {p.relative_to(root)}", file=sys.stderr)
            print("run: python3 scripts/build_catalog.py", file=sys.stderr)
            return 1
        print("catalog up to date")
        return 0

    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[p], encoding="utf-8")
    modules = json.loads(files[root / "catalog" / "modules.json"])
    c = modules["counts"]
    print(f"wrote {len(stale)} file(s); {c['total']} cards {c['by_disposition']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
