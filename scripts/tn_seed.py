#!/usr/bin/env python3
"""tn-seed CLI — community-seeding distribution run for a tenant (specs/003).

Loads the tenant's _distribution targets, fetches + scores + drafts contribution
briefs, and queues them for review. Live Reddit needs an OAuth fetch_json (pending);
use --fixture <listing.json> for an offline/dry run.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # snow-gloves-os/scripts
from lib.seed import load_targets, run_seed

ROOT = Path(__file__).resolve().parent.parent  # snow-gloves-os/


def resolve_distribution_dir(tenant):
    import yaml
    f = ROOT / "tenants" / tenant / "MANIFEST.yaml"
    if not f.exists():
        return None
    m = yaml.safe_load(f.read_text()) or {}
    d = (m.get("distribution") or {}).get("vault_path")
    return Path(d) if d else None


def main():
    ap = argparse.ArgumentParser(description="tn-seed — community-seeding run")
    ap.add_argument("--tenant", default="tryambakam-noesis")
    ap.add_argument("--distribution-dir", help="override the tenant's _distribution path")
    ap.add_argument("--fixture", help="JSON listing file for an offline run (no live Reddit)")
    ap.add_argument("--min-fit", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()

    dist = Path(a.distribution_dir) if a.distribution_dir else resolve_distribution_dir(a.tenant)
    if not dist or not (dist / "targets").exists():
        print(f"no _distribution/targets for tenant {a.tenant!r} (looked in {dist})", file=sys.stderr)
        sys.exit(2)

    targets = load_targets(dist)
    if not targets:
        print(f"no targets loaded from {dist}/targets", file=sys.stderr)
        sys.exit(2)

    if a.fixture:
        listing = json.loads(Path(a.fixture).read_text())
        fetch_json = lambda url: listing  # noqa: E731
    else:
        fetch_json = None  # live: lib.reddit._default_fetch_json (Reddit 403 until OAuth adapter lands)

    written = run_seed(targets, dist / "queue", fetch_json=fetch_json, min_fit=a.min_fit, limit=a.limit)
    print(f"tn-seed [{a.tenant}] targets={len(targets)} queued={len(written)}")
    for p in written:
        print("  ", p)


if __name__ == "__main__":
    main()
