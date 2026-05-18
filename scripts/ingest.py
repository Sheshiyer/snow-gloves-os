#!/usr/bin/env python3
"""Snow Gloves OS — file ingestion entrypoint.

Walks tenant source paths and prepares them for the embedding pipeline.
"""
import sys, os, yaml, json
from pathlib import Path

if len(sys.argv) < 2:
    print("usage: ingest.py <tenant-slug>")
    sys.exit(1)

tenant = sys.argv[1]
root = Path(__file__).resolve().parent.parent
tdir = root / "tenants" / tenant
manifest = tdir / "sources.yaml"
if not manifest.exists():
    print(f"missing: {manifest}")
    sys.exit(1)

cfg = yaml.safe_load(manifest.read_text())
out = tdir / "ingest-plan.json"
plan = {"tenant": tenant, "files": []}

for src in cfg.get("sources", []) or []:
    p = Path(src["path"]).expanduser()
    if not p.exists():
        print(f"skip (missing): {p}")
        continue
    if p.is_file():
        plan["files"].append({"path": str(p), "size": p.stat().st_size})
    else:
        for f in p.rglob("*"):
            if f.is_file() and not any(part.startswith(".") for part in f.parts):
                plan["files"].append({"path": str(f), "size": f.stat().st_size})

out.write_text(json.dumps(plan, indent=2))
print(f"wrote {out} ({len(plan['files'])} files)")
