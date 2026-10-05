#!/usr/bin/env python3
"""Snow Gloves OS — file ingestion entrypoint.

Walks tenant source paths and prepares them for the embedding pipeline.
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import paths  # noqa: E402
from lib.ingest_filters import iter_ingest_files  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ingest.py <tenant-slug>")
        sys.exit(1)

    tenant = sys.argv[1]

    tdir = paths.tenants_dir() / tenant
    manifest = tdir / "sources.yaml"
    if not manifest.exists():
        print(f"missing: {manifest}")
        sys.exit(1)

    cfg = yaml.safe_load(manifest.read_text()) or {}
    out = tdir / "ingest-plan.json"
    plan: dict = {"tenant": tenant, "files": [], "skipped": []}

    for src in cfg.get("sources", []) or []:
        if src.get("ingest") is False:
            continue
        raw = src["path"]
        p = Path(raw).expanduser()
        if not p.is_absolute() and not str(raw).startswith("~"):
            p = (root / p).resolve()
        if not p.exists():
            print(f"skip (missing): {p}")
            plan["skipped"].append({"path": str(p), "reason": "missing"})
            continue

        added, skipped = iter_ingest_files(
            p,
            include_glob=src.get("include_glob"),
            exclude_glob=src.get("exclude_glob"),
            max_file_bytes=src.get("max_file_bytes"),
        )
        plan["files"].extend(added)
        plan["skipped"].extend(skipped)

    seen: set[str] = set()
    unique_files: list[dict] = []
    for item in plan["files"]:
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        unique_files.append(item)
    plan["files"] = unique_files

    out.write_text(json.dumps(plan, indent=2))
    print(f"wrote {out} ({len(plan['files'])} files, {len(plan['skipped'])} skipped)")


if __name__ == "__main__":
    main()
