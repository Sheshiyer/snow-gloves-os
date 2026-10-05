#!/usr/bin/env python3
"""Fleet wing profiles (nodes/<wing>/node.yaml): list, show, enable, render.

    python3 scripts/fleet/node_profile.py list
    python3 scripts/fleet/node_profile.py show coding
    python3 scripts/fleet/node_profile.py enable --tenant acme --node marketing
    python3 scripts/fleet/node_profile.py enable --all-tenants --node marketing
    python3 scripts/fleet/node_profile.py render --tenant acme --node coding --runtime claude [--write] [--out DIR] [--project DIR]

A render is enabled.yaml[tenant] ∩ the wing's modules (and connectors), filtered
to enableable cards, plus the wing's MCP launch specs. Dry run unless --write.
The tenant's enabled.yaml stays the only authority connector-gate reads.

Exit codes: 0 ok, 1 usage or refusal, 2 node validation failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import onboard  # noqa: E402
from lib import nodes  # noqa: E402

CODE_ROOT = SCRIPTS.parent


class Parser(argparse.ArgumentParser):
    """Usage errors exit 1; exit 2 is reserved for node validation."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(1)


def catalog_for(args) -> onboard.Catalog:
    return onboard.Catalog(args.root, args.adapters_dir, args.catalog, data_root=args.data)


def validate(args, wing: str, node: dict, catalog: onboard.Catalog) -> list[str]:
    return nodes.validate_node(node, folder=wing, adapters_dir=args.adapters_dir, catalog=catalog if catalog.built else None)


def load_checked(args, wing: str, catalog: onboard.Catalog) -> dict:
    """Load and validate a wing. Missing -> SystemExit(message); invalid -> SystemExit(2)."""
    try:
        node = nodes.load_node(args.node_root, wing)
    except nodes.NodeError as exc:
        raise SystemExit(str(exc)) from None
    problems = validate(args, wing, node, catalog)
    if problems:
        print(f"nodes/{wing}/node.yaml is not valid:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(2)
    return node


def registry_tenants(root: Path) -> list[str]:
    path = root / "tenants" / "_registry.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[str] = []
    for entry in data.get("tenants") or []:
        slug = entry if isinstance(entry, str) else (entry.get("slug") or entry.get("id")) if isinstance(entry, dict) else None
        if isinstance(slug, str) and slug and not slug.startswith("_") and slug not in out:
            out.append(slug)
    return out


# ---------------------------------------------------------------- commands


def cmd_list(args) -> int:
    catalog = catalog_for(args)
    wings = nodes.list_nodes(args.node_root)
    if not wings:
        print(f"no node profiles under {nodes.nodes_dir(args.node_root)} (expected nodes/<wing>/node.yaml)")
        return 0
    for wing in wings:
        try:
            node = nodes.load_node(args.node_root, wing)
        except nodes.NodeError as exc:
            print(f"{wing:<10} unreadable: {exc}")
            continue
        problems = validate(args, wing, node, catalog)
        status = "ok" if not problems else f"{len(problems)} problem(s); run: show {wing}"
        print(
            f"{wing:<10} {node.get('hostname', '?'):<14} primary {node.get('primary', '?'):<9}"
            f" runtimes {','.join(node.get('runtimes') or []) or '-':<34}"
            f" modules {len(node.get('modules') or []):>3}  connectors {len(node.get('connectors') or []):>2}"
            f"  mcps {len(node.get('mcps') or {}):>2}  {status}"
        )
    return 0


def cmd_show(args) -> int:
    catalog = catalog_for(args)
    try:
        node = nodes.load_node(args.node_root, args.wing)
    except nodes.NodeError as exc:
        raise SystemExit(str(exc)) from None
    path = nodes.node_path(args.node_root, args.wing)
    print(f"# {path}")
    print(path.read_text(encoding="utf-8").rstrip("\n"))
    print()
    problems = validate(args, args.wing, node, catalog)
    if problems:
        print(f"validation: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    tenants = node.get("tenants", "all")
    served = "all tenants" if tenants in (None, "all") else f"{len(tenants)} listed tenant(s)"
    extra = "" if catalog.built else " (catalog not built: module ids were not checked)"
    print(
        f"validation: valid; {len(node.get('modules') or [])} modules, {len(node.get('connectors') or [])} connectors,"
        f" {len(node.get('mcps') or {})} mcps, serves {served}{extra}"
    )
    return 0


def cmd_enable(args) -> int:
    if bool(args.tenant) == bool(args.all_tenants):
        raise SystemExit("enable needs exactly one of --tenant <slug> or --all-tenants")
    catalog = catalog_for(args)
    node = load_checked(args, args.node, catalog)
    modules = node.get("modules") or []
    if not modules:
        print(f"node {args.node} lists no modules; nothing to enable")
        return 0
    slugs = [args.tenant] if args.tenant else registry_tenants(args.data)
    if not slugs:
        print(f"no tenants in {args.data / 'tenants' / '_registry.yaml'}")
        return 0
    for slug in slugs:
        tdir = args.data / "tenants" / slug
        if args.all_tenants and not tdir.is_dir():
            print(f"skip {slug}: registered but has no folder under {args.data / 'tenants'}", file=sys.stderr)
            continue
        if not nodes.node_serves(node, slug):
            print(f"skip {slug}: not served by the {args.node} wing (node.tenants)", file=sys.stderr)
            continue
        path = onboard.enable(catalog, slug, ",".join(modules), replace=False)
        ids, _agents = onboard.read_enabled(tdir)
        print(f"enable {args.node} -> {slug}: wrote {path} ({len(ids)} modules)")
    connectors = node.get("connectors") or []
    if connectors:
        print(f"note: wing connectors ({', '.join(connectors)}) are never auto-enabled; "
              f"enable them per tenant with scripts/onboard.py --enable")
    return 0


def cmd_render(args) -> int:
    catalog = catalog_for(args)
    node = load_checked(args, args.node, catalog)
    return onboard.render(catalog, args.runtime, args.tenant, args.out, args.project, args.write, node=node)


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = Parser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--root", type=Path, default=None,
                   help="Snow Gloves checkout (default: $SNOWGLOVES_ROOT or this one); holds tenants/ and nodes/ too unless --data")
    p.add_argument("--data", type=Path, default=None,
                   help="instance data checkout holding tenants/ and nodes/ (default: $SNOWGLOVES_DATA, else the checkout)")
    p.add_argument("--adapters-dir", type=Path, default=CODE_ROOT / "adapters", help=argparse.SUPPRESS)
    p.add_argument("--catalog", type=Path, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    s = sub.add_parser("list", help="list wings with a validation status")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="print a wing's node.yaml and its validation result")
    s.add_argument("wing")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("enable", help="add a wing's modules to a tenant's enabled.yaml (additive, idempotent)")
    s.add_argument("--node", required=True, metavar="WING")
    s.add_argument("--tenant", metavar="SLUG")
    s.add_argument("--all-tenants", action="store_true", help="every tenant in tenants/_registry.yaml")
    s.set_defaults(func=cmd_enable)

    s = sub.add_parser("render", help="render enabled ∩ wing for one runtime (dry run unless --write)")
    s.add_argument("--node", required=True, metavar="WING")
    s.add_argument("--tenant", required=True, metavar="SLUG")
    s.add_argument("--runtime", required=True, metavar="RT")
    s.add_argument("--write", action="store_true")
    s.add_argument("--out", type=Path, help="render under this folder instead of real paths")
    s.add_argument("--project", type=Path, help="project folder for {project} paths")
    s.set_defaults(func=cmd_render)

    args = p.parse_args(argv)
    args.root, args.data, args.node_root = onboard.resolve_roots(args.root, args.data)
    try:
        return args.func(args)
    except onboard.ad.AdapterError as exc:
        print(f"node_profile: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(f"node_profile: {exc.code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
