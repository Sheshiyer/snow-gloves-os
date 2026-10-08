"""Cockpit snapshot, document reader, and preview plan generator.

Strict security rules:
- Read-only: never mkdir, write, or modify mtimes.
- No subprocess/shell execution.
- No imports of hermes, onboard, or any module that creates audit dirs.
- Zero credential, secret, environment, or private host leakages.
- Strict bounds on all file reads, payloads, and traversals.
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.request
import urllib.error
import yaml
from lib import paths
from lib.redact import redact_text
from lib.cockpit_brand_summary import brand_summary

MAX_FILE_BYTES = 4 * 1024 * 1024       # 4 MB max YAML/JSON
MAX_CATALOG_BYTES = 1 * 1024 * 1024    # 1 MB max catalog
MAX_DOC_BYTES = 128 * 1024             # 128 KiB max doc read
MAX_ACCEPTANCE_BYTES = 256 * 1024      # Ledger history grows independently of document previews
MAX_AUDIT_TAIL_BYTES = 256 * 1024      # 256 KiB max audit tail
MAX_AUDIT_LINE_BYTES = 8 * 1024        # 8 KiB per audit line
MAX_AUDIT_RECORDS = 100
MAX_TENANTS = 128

SLUG_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,63}$")
MODULE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")

ALLOWED_DOC_PREFIXES = (
    "README.md",
    'scripts/hermes.py',
    'scripts/ingest.py',
    'scripts/embed_worker.py',
    'scripts/paperclip_bridge.py',
    'scripts/sentinel_sweep.py',
    'scripts/lib/adapters.py',
    'catalog/modules.json',
    'connectors/g-stack/capabilities.yaml',
    'docs/architecture/knowledge-ingest.md',
    'docs/fleet/README.md',
    'docs/fleet/04-GATEWAY.md',
    'docs/fleet/08-CLOUD-GATEWAY.md',
    'nodes/coding/node.yaml',
    'nodes/marketing/node.yaml',
    'nodes/design/node.yaml',
    'skills/tn-seed/SKILL.md',
    'skills/gtm-brief-synthesis/SKILL.md',

    "docs/architecture-overview.md",
    "docs/catalog.md",
    "docs/adapters.md",
    "docs/onboarding.md",
    "docs/infra-cockpit.md",
    "docs/OPS-WORKSPACE.md",
    "docs/SESSION-WORLD-DESIGN.md",
    "docs/FLEET-CONTROL-PLANE-PLAN.md",
    "docs/fleet/09-RUNTIME-SUPERVISOR.md",
    "catalog/SCHEMA.md",
    "workflows/skill-hooks.yaml",
    "workflows/constraints.yaml",
    "skills/registry.yaml",
    "skills/connector-gate/SKILL.md",
    "skills/sg-onboard/SKILL.md",
)

ALLOWED_AGENT_DOC_NAMES = {"IDENTITY.md", "SOUL.md", "TOOLS.md", "SKILLS.md", "HEARTBEAT.md"}


def _safe_label(value: str, limit: int = 128) -> str:
    value = re.sub(r"(?i)(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+", "[secret]", value)
    return redact_text(value)[:limit]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_safe_path(base: Path, target: Path) -> bool:
    try:
        base_resolved = base.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        # Target must be relative to base
        target_resolved.relative_to(base_resolved)
        # Check for any symlink from target up to base
        curr = target
        while True:
            if curr.is_symlink():
                return False
            if curr.resolve(strict=False) == base_resolved or curr == base or curr.parent == curr:
                break
            curr = curr.parent
        return True
    except Exception:
        return False


def _safe_read_text(path: Path, max_bytes: int = MAX_FILE_BYTES, reject_oversize: bool = False) -> Optional[str]:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        with open(path, "rb") as f:
            raw = f.read(max_bytes + 1)
            if len(raw) > max_bytes:
                if reject_oversize:
                    return None
                raw = raw[:max_bytes]
            return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_yaml(path: Path, max_bytes: int = MAX_FILE_BYTES) -> Optional[Any]:
    text = _safe_read_text(path, max_bytes=max_bytes, reject_oversize=True)
    if text is None:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:
        return None


def _safe_load_json(path: Path, max_bytes: int = MAX_FILE_BYTES) -> Optional[Any]:
    text = _safe_read_text(path, max_bytes=max_bytes, reject_oversize=True)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _load_catalog(repo_root: Path) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    warnings: List[Dict[str, str]] = []
    cat_path = repo_root / "catalog" / "modules.json"
    if not _is_safe_path(repo_root, cat_path) or not cat_path.exists():
        warnings.append({"code": "missing_catalog", "message": "catalog/modules.json not found"})
        return {}, warnings

    data = _safe_load_json(cat_path, max_bytes=MAX_CATALOG_BYTES)
    if not isinstance(data, dict):
        warnings.append({"code": "invalid_catalog", "message": "catalog/modules.json invalid JSON shape"})
        return {}, warnings

    out = {
        "cards": data.get("cards", []),
        "agents": data.get("agents", []),
        "adapters": data.get("adapters", []),
        "connectors": data.get("connectors", []),
    }
    if "schema" in data:
        out["schema"] = data["schema"]
    if "version" in data:
        out["version"] = data["version"]
    if "counts" in data:
        out["counts"] = data["counts"]
    return out, warnings


def _load_approvals_counts(app_dir: Path, base_root: Path) -> Tuple[Dict[str, int], int]:
    app_counts = {"pending": 0, "approved": 0, "rejected": 0}
    malformed_count = 0
    if not app_dir.exists() or not app_dir.is_dir() or app_dir.is_symlink() or not _is_safe_path(base_root, app_dir):
        return app_counts, malformed_count

    try:
        for app_file in sorted(app_dir.iterdir()):
            if not app_file.is_file() or app_file.is_symlink() or not _is_safe_path(base_root, app_file):
                continue
            if app_file.name == "pending.jsonl":
                recs, mal = _tail_jsonl(app_file, max_records=MAX_AUDIT_RECORDS)
                malformed_count += mal
                for r in recs:
                    if r.get("tenant") != app_dir.parent.name:
                        continue
                    st = str(r.get("status", r.get("decision", "pending"))).lower()
                    if st in app_counts:
                        app_counts[st] += 1
                    else:
                        app_counts["pending"] += 1
            elif app_file.name == "history.jsonl":
                recs, mal = _tail_jsonl(app_file, max_records=MAX_AUDIT_RECORDS)
                malformed_count += mal
                for r in recs:
                    if r.get("tenant") != app_dir.parent.name:
                        continue
                    st = str(r.get("status", r.get("decision", ""))).lower()
                    if st in app_counts:
                        app_counts[st] += 1
            elif app_file.suffix in (".yaml", ".yml"):
                adata = _safe_load_yaml(app_file, max_bytes=64 * 1024)
                if isinstance(adata, dict):
                    st = str(adata.get("status", adata.get("decision", ""))).lower()
                    if st in app_counts:
                        app_counts[st] += 1
                elif adata is not None:
                    malformed_count += 1
            elif app_file.suffix == ".json":
                adata = _safe_load_json(app_file, max_bytes=64 * 1024)
                if isinstance(adata, dict):
                    st = str(adata.get("status", adata.get("decision", ""))).lower()
                    if st in app_counts:
                        app_counts[st] += 1
                elif adata is not None:
                    malformed_count += 1
    except Exception:
        pass
    return app_counts, malformed_count


def _load_tenants(repo_root: Path, data_root: Optional[Path], filter_tenant: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    tenants: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    total_malformed_approvals = 0

    target_base = (data_root / "tenants") if data_root is not None else (repo_root / "tenants")
    is_local = data_root is not None

    if not target_base.exists() or not target_base.is_dir() or target_base.is_symlink():
        if filter_tenant:
            raise ValueError("unknown_tenant")
        return [], warnings

    try:
        entries = sorted(list(target_base.iterdir()))
    except Exception:
        entries = []

    if filter_tenant and filter_tenant not in [e.name for e in entries if e.is_dir() and not e.is_symlink()]:
        raise ValueError("unknown_tenant")

    count = 0
    for entry in entries:
        if count >= MAX_TENANTS:
            break
        if not entry.is_dir() or entry.is_symlink():
            continue
        slug = entry.name
        if not SLUG_RE.match(slug):
            continue
        if filter_tenant and slug != filter_tenant:
            continue

        t_warnings: List[str] = []
        manifest_path = entry / "MANIFEST.yaml"
        name = slug
        if manifest_path.exists() and _is_safe_path(target_base, manifest_path):
            mdata = _safe_load_yaml(manifest_path)
            if isinstance(mdata, dict):
                raw_name = mdata.get("name") or mdata.get("business_name")
                if isinstance(raw_name, str) and len(raw_name) <= 128:
                    name = _safe_label(raw_name)

        primary_runtime = None
        if not (entry / "runtime.yaml").is_file():
            t_warnings.append("runtime configuration unavailable")
        if not (entry / "enabled.yaml").is_file():
            t_warnings.append("module enablement configuration unavailable")
        runtime_path = entry / "runtime.yaml"
        if runtime_path.exists() and _is_safe_path(target_base, runtime_path):
            rdata = _safe_load_yaml(runtime_path)
            if isinstance(rdata, dict):
                pr = rdata.get("primary") or rdata.get("runtime")
                if isinstance(pr, str) and len(pr) <= 64:
                    primary_runtime = pr

        agents: List[str] = []
        enabled_modules: List[str] = []
        enabled_path = entry / "enabled.yaml"
        if enabled_path.exists() and _is_safe_path(target_base, enabled_path):
            edata = _safe_load_yaml(enabled_path)
            if isinstance(edata, dict):
                raw_agents = edata.get("agents", [])
                if isinstance(raw_agents, list):
                    agents = [str(a) for a in raw_agents if isinstance(a, str) and len(a) <= 64]
                raw_mods = edata.get("modules", [])
                if isinstance(raw_mods, list):
                    for m in raw_mods:
                        if isinstance(m, dict) and "id" in m:
                            enabled_modules.append(str(m["id"]))
                        elif isinstance(m, str):
                            enabled_modules.append(m)

        source_count = 0
        sdata = None
        sources_path = entry / "sources.yaml"
        if sources_path.exists() and _is_safe_path(target_base, sources_path):
            sdata = _safe_load_yaml(sources_path)
            if isinstance(sdata, dict) and isinstance(sdata.get("sources"), list):
                source_count = len(sdata["sources"])
            elif isinstance(sdata, list):
                source_count = len(sdata)

        sources_ref = [f"tenants/{slug}/sources.yaml"] if not is_local else [f"data:tenant:{slug}:sources"]

        app_dir = entry / "approvals"
        app_counts, app_malformed = _load_approvals_counts(app_dir, target_base)
        total_malformed_approvals += app_malformed

        tenants.append({
            "slug": slug,
            "name": name,
            "primaryRuntime": primary_runtime,
            "agents": sorted(list(set(agents))),
            "enabledModules": sorted(list(set(enabled_modules))),
            "approvalCounts": app_counts,
            "sourceCount": source_count,
            "sources": sources_ref,
            "availability": "local" if is_local else "fixture",
            "warnings": t_warnings,
        })
        if is_local:
            try:
                tenants[-1].update(brand_summary(data_root, entry, sdata if sources_path.exists() and _is_safe_path(target_base, sources_path) else None))
            except (ValueError, OSError):
                tenants[-1]["warnings"].append("brand summary unavailable")
        count += 1

    if total_malformed_approvals > 0:
        warnings.append({"code": "approvals_malformed_rows", "message": f"{total_malformed_approvals} malformed approval records ignored"})

    return tenants, warnings


def _load_fleet(repo_root: Path, data_root: Optional[Path]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    fleet: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []

    target_base = data_root if data_root is not None else repo_root
    fleet_yaml = target_base / "fleet.yaml"
    if not fleet_yaml.exists() or not _is_safe_path(target_base, fleet_yaml):
        warnings.append({"code": "missing_fleet", "message": "fleet.yaml missing"})

    target_nodes_dir = target_base / "nodes"
    is_local = data_root is not None

    if target_nodes_dir.exists() and target_nodes_dir.is_dir() and not target_nodes_dir.is_symlink() and _is_safe_path(target_base, target_nodes_dir):
        try:
            for wing_dir in sorted(target_nodes_dir.iterdir()):
                if not wing_dir.is_dir() or wing_dir.is_symlink() or not _is_safe_path(target_base, wing_dir):
                    continue
                node_yaml = wing_dir / "node.yaml"
                if not node_yaml.exists() or node_yaml.is_symlink() or not _is_safe_path(target_base, node_yaml):
                    continue
                ndata = _safe_load_yaml(node_yaml)
                if not isinstance(ndata, dict):
                    continue

                raw_wing = ndata.get("wing", wing_dir.name)
                wing = str(raw_wing) if isinstance(raw_wing, str) and SLUG_RE.match(raw_wing) else wing_dir.name
                primary = ndata.get("primary")
                primary = primary if isinstance(primary, str) and MODULE_ID_RE.fullmatch(primary) else None
                runtimes = [str(r) for r in ndata.get("runtimes", [primary]) if isinstance(r, str) and MODULE_ID_RE.fullmatch(r)] if isinstance(ndata.get("runtimes"), list) else [primary]
                modules = [str(m) for m in ndata.get("modules", []) if isinstance(m, str) and MODULE_ID_RE.match(m)]
                connectors = [str(c) for c in ndata.get("connectors", []) if isinstance(c, str) and MODULE_ID_RE.match(c)]

                safe_services = []
                raw_services = ndata.get("services", [])
                if isinstance(raw_services, list):
                    for s in raw_services:
                        if isinstance(s, dict):
                            safe_s = {}
                            if "id" in s and isinstance(s["id"], str) and MODULE_ID_RE.fullmatch(s["id"]):
                                safe_s["id"] = str(s["id"])
                            if "port" in s and isinstance(s["port"], int) and not isinstance(s["port"], bool) and 1 <= s["port"] <= 65535:
                                safe_s["port"] = s["port"]
                            if safe_s:
                                safe_services.append(safe_s)

                profile = {
                    "wing": wing,
                    "primary": primary,
                    "runtimes": runtimes,
                    "modules": modules,
                    "connectors": connectors,
                    "services": safe_services,
                }

                sources_ref = [f"nodes/{wing}/node.yaml"] if not is_local else [f"data:nodes:{wing}:node"]
                node_id = f"node-{wing}"
                fleet.append({
                    "id": node_id,
                    "name": wing.capitalize() + " Wing Node",
                    "wing": wing,
                    "runtime": primary,
                    "profile": profile,
                    "sources": sources_ref,
                    "evidence": "local" if is_local else "source",
                })
        except Exception:
            pass

    if _is_safe_path(target_base, fleet_yaml) and fleet_yaml.is_file():
        warnings.append({"code": "inventory_not_projected", "message": "Fleet inventory exists; only sanitized node profiles are projected"})
    return fleet, warnings


def _tail_jsonl(path: Path, max_records: int = MAX_AUDIT_RECORDS) -> Tuple[List[Dict[str, Any]], int]:
    malformed = 0
    if not path.is_file() or path.is_symlink():
        return [], 0
    try:
        size = path.stat().st_size
        read_size = min(size, MAX_AUDIT_TAIL_BYTES)
        with open(path, "rb") as f:
            if size > read_size:
                f.seek(size - read_size)
            raw = f.read(read_size)

        lines = raw.split(b"\n")
        records = []
        for line in lines:
            if not line.strip():
                continue
            if len(line) > MAX_AUDIT_LINE_BYTES:
                malformed += 1
                continue
            try:
                parsed = json.loads(line.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    records.append(parsed)
                else:
                    malformed += 1
            except Exception:
                malformed += 1
        return records[-max_records:], malformed
    except Exception:
        return [], 1


def _load_activity(
    repo_root: Path,
    data_root: Optional[Path],
    tenant: Optional[str],
    mode: str
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, str]]]:
    events: List[Dict[str, Any]] = []
    jobs: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    approvals: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    malformed_count = 0

    if not tenant:
        return {"events": [], "jobs": [], "artifacts": [], "approvals": []}, warnings

    files_to_check: List[Tuple[Path, str, Optional[str]]] = []
    bound_root = data_root if mode == "local-private" else repo_root
    if bound_root is None:
        return {"events": [], "jobs": [], "artifacts": [], "approvals": []}, warnings

    if mode == "local-private" and data_root is not None:
        audit_dir = data_root / "_audit"
        files_to_check.extend([
            (audit_dir / "hermes-events.jsonl", "events", None),
            (audit_dir / "jobs.jsonl", "jobs", None),
            (audit_dir / "artifacts.jsonl", "artifacts", None),
            (audit_dir / "approvals.jsonl", "approvals", None),
        ])
        t_audit = data_root / "tenants" / tenant / "audit"
        files_to_check.extend([
            (t_audit / "events.jsonl", "events", None),
            (t_audit / "jobs.jsonl", "jobs", None),
            (t_audit / "artifacts.jsonl", "artifacts", None),
            (t_audit / "approvals.jsonl", "approvals", None),
        ])
        t_app = data_root / "tenants" / tenant / "approvals"
        files_to_check.extend([
            (t_app / "pending.jsonl", "approvals", "pending"),
            (t_app / "history.jsonl", "approvals", None),
        ])
    else:
        t_audit = repo_root / "tenants" / tenant / "audit"
        files_to_check.extend([
            (t_audit / "events.jsonl", "events", None),
            (t_audit / "jobs.jsonl", "jobs", None),
            (t_audit / "artifacts.jsonl", "artifacts", None),
            (t_audit / "approvals.jsonl", "approvals", None),
        ])
        t_app = repo_root / "tenants" / tenant / "approvals"
        files_to_check.extend([
            (t_app / "pending.jsonl", "approvals", "pending"),
            (t_app / "history.jsonl", "approvals", None),
        ])

    for p, kind_type, force_status in files_to_check:
        if not p.exists():
            continue
        if not _is_safe_path(bound_root, p):
            warnings.append({"code": "unsafe_activity_path", "message": "Activity source held"})
            continue
        recs, mal = _tail_jsonl(p)
        malformed_count += mal
        for r in recs:
            rec_tenant = r.get("tenant")
            # Absent tenant or mismatched tenant excluded
            if rec_tenant is None or rec_tenant != tenant:
                continue

            # Extract actual timestamp or ts or created_at, else null
            raw_ts = r.get("timestamp") if "timestamp" in r else (r.get("ts") if "ts" in r else r.get("created_at"))
            ts = None
            if isinstance(raw_ts, int) and not isinstance(raw_ts, bool) and len(str(raw_ts)) <= 21:
                ts = str(raw_ts)
            elif isinstance(raw_ts, float) and math.isfinite(raw_ts):
                ts = str(raw_ts)[:128]
            elif isinstance(raw_ts, str) and len(raw_ts) <= 128:
                try:
                    datetime.datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    ts = raw_ts
                except ValueError:
                    if re.fullmatch(r"-?\d{1,20}(?:\.\d{1,9})?", raw_ts):
                        ts = raw_ts

            # Extract actual status
            if force_status is not None:
                status = force_status
            else:
                raw_st = r.get("status") if "status" in r else r.get("decision")
                status = _safe_label(str(raw_st), 64) if raw_st is not None and isinstance(raw_st, (str, int, float)) else "unknown"

            r_id = str(r.get("id")) if r.get("id") is not None and isinstance(r.get("id"), (str, int)) else hashlib.sha256(json.dumps(r, sort_keys=True).encode("utf-8")).hexdigest()[:12]
            agent = str(r.get("agent")) if r.get("agent") is not None and isinstance(r.get("agent"), (str, int)) else None
            kind = str(r.get("kind", kind_type)) if isinstance(r.get("kind", kind_type), str) else kind_type
            job_id = str(r.get("jobId", r.get("job_id"))) if (r.get("jobId") is not None or r.get("job_id") is not None) else None
            artifact_id = str(r.get("artifactId", r.get("artifact_id"))) if (r.get("artifactId") is not None or r.get("artifact_id") is not None) else None

            safe_summary = _safe_label(f"{kind} ({status}) for {agent or 'system'}", 200)

            item = {
                "id": _safe_label(r_id),
                "timestamp": ts,
                "tenant": tenant,
                "agent": _safe_label(agent, 64) if agent else None,
                "kind": _safe_label(kind),
                "status": status,
                "jobId": _safe_label(job_id) if isinstance(job_id, str) else None,
                "artifactId": _safe_label(artifact_id) if isinstance(artifact_id, str) else None,
                "summary": safe_summary,
            }

            if kind_type == "events":
                events.append(item)
            elif kind_type == "jobs":
                jobs.append(item)
            elif kind_type == "artifacts":
                artifacts.append(item)
            elif kind_type == "approvals":
                approvals.append(item)

    if malformed_count > 0:
        warnings.append({"code": "audit_malformed_rows", "message": f"{malformed_count} malformed audit records ignored"})

    return {
        "events": events[-MAX_AUDIT_RECORDS:],
        "jobs": jobs[-MAX_AUDIT_RECORDS:],
        "artifacts": artifacts[-MAX_AUDIT_RECORDS:],
        "approvals": approvals[-MAX_AUDIT_RECORDS:],
    }, warnings


def _load_acceptance(repo_root: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    acceptance: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    isa_path = repo_root / "ISA.md"
    if not _is_safe_path(repo_root, isa_path) or not isa_path.is_file():
        return acceptance, warnings

    content = _safe_read_text(isa_path, max_bytes=MAX_ACCEPTANCE_BYTES, reject_oversize=True)
    if not content:
        warnings.append({"code": "acceptance_unavailable", "message": "Acceptance ledger unreadable or exceeds its bounded reader limit."})
        return acceptance, warnings

    # Only parse markdown checkbox ISC criterion lines: e.g. - [x] ISC-101: description or - [ ] ISC-102: desc
    # or table checkbox rows with ISC ID
    checkbox_pattern = re.compile(r"^[-*]\s+\[([ xX])\]\s+(?:`?)(ISC-[A-Za-z0-9_-]+)(?:`?)(?::|\s+-|\s+)(.*)$", re.IGNORECASE)
    table_checkbox_pattern = re.compile(r"^\|\s*\[([ xX])\]\s*\|\s*(ISC-[A-Za-z0-9_-]+)\s*\|\s*([^|]+)\|", re.IGNORECASE)

    for line in content.splitlines():
        line = line.strip()
        m1 = checkbox_pattern.match(line)
        if m1:
            checked, raw_id, raw_crit = m1.group(1), m1.group(2), m1.group(3)
            st = "accepted" if checked.lower() == "x" else "open"
            crit = redact_text(raw_crit.strip())[:200]
            acceptance.append({
                "id": raw_id,
                "criterion": crit,
                "status": st,
                "source": "ISA.md",
            })
            continue
        m2 = table_checkbox_pattern.match(line)
        if m2:
            checked, raw_id, raw_crit = m2.group(1), m2.group(2), m2.group(3)
            st = "accepted" if checked.lower() == "x" else "open"
            crit = redact_text(raw_crit.strip())[:200]
            acceptance.append({
                "id": raw_id,
                "criterion": crit,
                "status": st,
                "source": "ISA.md",
            })

    if len(acceptance) > 1024:
        warnings.append({"code": "acceptance_truncated", "message": "Acceptance ledger exceeds 1024 criteria."})
    return acceptance[:1024], warnings


def _load_routing(repo_root: Path) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    warnings: List[Dict[str, str]] = []
    rules: List[Dict[str, Any]] = []
    skills_registry: List[Dict[str, Any]] = []

    # 1. workflows/constraints.yaml
    c_path = repo_root / "workflows" / "constraints.yaml"
    if c_path.exists() and _is_safe_path(repo_root, c_path):
        cdata = _safe_load_yaml(c_path)
        if isinstance(cdata, dict) and isinstance(cdata.get("constraints"), list):
            for c in cdata["constraints"]:
                if isinstance(c, dict):
                    when = c.get("when", {})
                    then = c.get("then", {})
                    globs = when.get("globs", []) if isinstance(when.get("globs"), list) else []
                    rules.append({
                        "id": str(c.get("id", f"constraint-{len(rules)}")),
                        "agent": str(then.get("agent", "chief-of-staff")),
                        "hook": str(then.get("hook", "evaluate")),
                        "globs": [str(g) for g in globs],
                        "skills": [str(s) for s in then.get("skills", []) if isinstance(s, str)],
                        "source": "workflows/constraints.yaml",
                    })

    # 2. workflows/skill-hooks.yaml
    sh_path = repo_root / "workflows" / "skill-hooks.yaml"
    if sh_path.exists() and _is_safe_path(repo_root, sh_path):
        shdata = _safe_load_yaml(sh_path)
        if isinstance(shdata, dict) and isinstance(shdata.get("hooks"), list):
            for h in shdata["hooks"]:
                if isinstance(h, dict):
                    rules.append({
                        "id": str(h.get("id", f"hook-{len(rules)}")),
                        "agent": str(h.get("agent", "chief-of-staff")),
                        "hook": str(h.get("name", "default")),
                        "globs": [str(g) for g in h.get("globs", []) if isinstance(g, str)],
                        "skills": [str(s) for s in h.get("skills", []) if isinstance(s, str)],
                        "source": "workflows/skill-hooks.yaml",
                    })

    if sh_path.exists() and _is_safe_path(repo_root, sh_path):
        shdata = _safe_load_yaml(sh_path)
        routing = shdata.get("routing", {}) if isinstance(shdata, dict) else {}
        if isinstance(routing, dict):
            for agent, cfg in routing.items():
                if not isinstance(cfg, dict):
                    continue
                for hook in cfg.get("hooks", []) or []:
                    if not isinstance(hook, dict) or not isinstance(hook.get("id"), str):
                        continue
                    rules.append({"id": hook["id"], "agent": str(agent), "hook": hook["id"],
                                  "globs": [g for g in hook.get("globs", []) if isinstance(g, str)],
                                  "skills": [v for v in hook.get("skills", []) if isinstance(v, str)],
                                  "source": "workflows/skill-hooks.yaml"})

    # 3. skills/registry.yaml
    sr_path = repo_root / "skills" / "registry.yaml"
    if sr_path.exists() and _is_safe_path(repo_root, sr_path):
        srdata = _safe_load_yaml(sr_path)
        if isinstance(srdata, dict):
            agents_map = srdata.get("agents", {})
            if isinstance(agents_map, dict):
                for ag, sk_list in agents_map.items():
                    if isinstance(sk_list, list):
                        for sk in sk_list:
                            if isinstance(sk, str):
                                skills_registry.append({
                                    "id": sk,
                                    "agent": str(ag),
                                    "source": "skills/registry.yaml",
                                })

    return {"rules": rules, "skills": skills_registry}, warnings


def _load_documents_list(repo_root: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []

    cards_dir = repo_root / "catalog" / "cards"
    if _is_safe_path(repo_root, cards_dir) and cards_dir.is_dir():
        for card in sorted(cards_dir.glob("*.md"))[:256]:
            if _is_safe_path(repo_root, card) and card.is_file():
                docs.append({"path": str(card.relative_to(repo_root)), "title": card.stem,
                             "kind": "md", "bytes": card.stat().st_size})

    # Static allowlist
    for rel in ALLOWED_DOC_PREFIXES:
        p = repo_root / rel
        if p.is_file() and _is_safe_path(repo_root, p):
            try:
                st = p.stat()
                docs.append({
                    "path": rel,
                    "title": p.stem,
                    "kind": p.suffix.lstrip("."),
                    "bytes": st.st_size,
                })
            except Exception:
                pass

    # Dynamic agents/*/{IDENTITY,SOUL,TOOLS,SKILLS,HEARTBEAT}.md
    agents_dir = repo_root / "agents"
    if agents_dir.is_dir() and not agents_dir.is_symlink():
        try:
            for ag in sorted(agents_dir.iterdir()):
                if ag.is_dir() and not ag.is_symlink():
                    for doc_name in ALLOWED_AGENT_DOC_NAMES:
                        doc_p = ag / doc_name
                        if doc_p.is_file() and _is_safe_path(repo_root, doc_p):
                            rel = f"agents/{ag.name}/{doc_name}"
                            docs.append({
                                "path": rel,
                                "title": f"{ag.name} {doc_p.stem}",
                                "kind": "md",
                                "bytes": doc_p.stat().st_size,
                            })
        except Exception:
            pass

    # Dynamic adapters/*/adapter.yaml
    adapters_dir = repo_root / "adapters"
    if adapters_dir.is_dir() and not adapters_dir.is_symlink():
        try:
            for ad in sorted(adapters_dir.iterdir()):
                if ad.is_dir() and not ad.is_symlink():
                    ad_yaml = ad / "adapter.yaml"
                    if ad_yaml.is_file() and _is_safe_path(repo_root, ad_yaml):
                        rel = f"adapters/{ad.name}/adapter.yaml"
                        docs.append({
                            "path": rel,
                            "title": f"{ad.name} adapter",
                            "kind": "yaml",
                            "bytes": ad_yaml.stat().st_size,
                        })
        except Exception:
            pass

    return sorted(docs, key=lambda d: d["path"])


def _probe_services(probe: bool) -> List[Dict[str, Any]]:
    endpoints = [
        ("hermes", "Hermes", "http://127.0.0.1:4100/healthz", "json"),
        ("manifest", "Manifest", "http://127.0.0.1:8766/health", "json"),
        ("omniroute", "OmniRoute", "http://127.0.0.1:20128/healthz", "exact_ok"),
    ]
    services = []
    now = _now_iso()

    for sid, label, url, check_type in endpoints:
        if not probe:
            services.append({
                "id": sid,
                "label": label,
                "url": url,
                "state": "unknown",
                "checkedAt": None,
                "latencyMs": None,
                "scope": "endpoint-only",
            })
            continue

        t0 = datetime.datetime.now()
        state = "unknown"
        latency: Optional[float] = None
        try:
            # Disallow redirects via custom handler if needed, or urlopen standard
            req = urllib.request.Request(url, method="GET")
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(req, timeout=0.5) as resp:
                latency = round((datetime.datetime.now() - t0).total_seconds() * 1000, 2)
                code = resp.getcode()
                raw_body = resp.read(4096)
                if code == 200:
                    if check_type == "json":
                        try:
                            jb = json.loads(raw_body.decode("utf-8", errors="ignore"))
                            if isinstance(jb, dict) and jb.get("ok") is True:
                                state = "reachable"
                            else:
                                state = "unknown"
                        except Exception:
                            state = "unknown"
                    elif check_type == "exact_ok":
                        txt = raw_body.decode("utf-8", errors="ignore").strip()
                        if txt == "ok":
                            state = "reachable"
                        else:
                            state = "unknown"
                else:
                    state = "unknown"
        except urllib.error.HTTPError as e:
            latency = round((datetime.datetime.now() - t0).total_seconds() * 1000, 2)
            if e.code in (401, 403):
                state = "auth-required"
            else:
                state = "unreachable"
        except Exception:
            state = "unreachable"

        services.append({
            "id": sid,
            "label": label,
            "url": url,
            "state": state,
            "checkedAt": now,
            "latencyMs": latency,
            "scope": "endpoint-only",
        })
    return services


def build_snapshot(
    repo_root: Path,
    data_root: Optional[Path] = None,
    tenant: Optional[str] = None,
    probe: bool = True
) -> Dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    data_root = paths.data_root(data_root) if data_root is not None else None
    if tenant is not None and (not isinstance(tenant, str) or SLUG_RE.fullmatch(tenant) is None):
        raise ValueError("invalid_tenant")
    mode = "local-private" if data_root is not None else "public-fixtures"
    all_warnings: List[Dict[str, str]] = []

    catalog, cat_warn = _load_catalog(repo_root)
    all_warnings.extend(cat_warn)

    tenants, t_warn = _load_tenants(repo_root, data_root, tenant)
    all_warnings.extend(t_warn)

    fleet, fl_warn = _load_fleet(repo_root, data_root)
    all_warnings.extend(fl_warn)

    activity, act_warn = _load_activity(repo_root, data_root, tenant, mode)
    all_warnings.extend(act_warn)

    acceptance, acc_warn = _load_acceptance(repo_root)
    all_warnings.extend(acc_warn)

    routing, rt_warn = _load_routing(repo_root)
    all_warnings.extend(rt_warn)

    documents = _load_documents_list(repo_root)
    services = _probe_services(probe)

    return {
        "schema": "snowgloves.cockpit.v1",
        "generatedAt": _now_iso(),
        "scope": {
            "mode": mode,
            "tenant": tenant,
            "readOnly": True,
        },
        "catalog": catalog,
        "tenants": tenants,
        "fleet": fleet,
        "activity": activity,
        "acceptance": acceptance,
        "routing": routing,
        "documents": documents,
        "services": services,
        "warnings": all_warnings,
        "capabilities": {
            "documents": True,
            "planPreview": True,
            "execute": False,
            "enable": False,
            "approve": False,
        }
    }


def read_document(repo_root: Path, path: str) -> Dict[str, Any]:
    # Path normalize disallow absolute, dotdot, backslash, NUL, encoded %
    if not path or "\0" in path or ".." in path or "\\" in path or "%" in path or path.startswith("/"):
        raise ValueError("invalid_path")

    allowed_list = _load_documents_list(repo_root)
    allowed_paths = {d["path"] for d in allowed_list}
    if path not in allowed_paths:
        raise FileNotFoundError("document_not_allowed")

    doc_path = repo_root / path
    if not _is_safe_path(repo_root, doc_path) or not doc_path.is_file():
        raise FileNotFoundError("document_not_found")

    stat = doc_path.stat()
    file_bytes = stat.st_size

    with open(doc_path, "rb") as f:
        raw = f.read(MAX_DOC_BYTES + 1)

    truncated = len(raw) > MAX_DOC_BYTES
    slice_bytes = raw[:MAX_DOC_BYTES]
    sha256 = hashlib.sha256(slice_bytes).hexdigest()
    content = slice_bytes.decode("utf-8", errors="replace")

    return {
        "schema": "snowgloves.cockpit.document.v1",
        "path": path,
        "title": doc_path.stem,
        "kind": doc_path.suffix.lstrip("."),
        "bytes": file_bytes,
        "content": content,
        "sha256": sha256,
        "truncated": truncated,
        "source": "public-repo",
    }


def preview_plan(repo_root: Path, payload: Dict[str, Any], data_root: Optional[Path] = None) -> Dict[str, Any]:
    allowed_keys = {"tenant", "title", "modules", "runtime", "wing"}
    if not isinstance(payload, dict) or not (set(payload.keys()) <= allowed_keys):
        raise ValueError("invalid_payload_keys")

    tenant = payload.get("tenant")
    if not isinstance(tenant, str) or not SLUG_RE.match(tenant):
        raise ValueError("invalid_tenant_slug")

    title = payload.get("title")
    if not isinstance(title, str) or not (1 <= len(title) <= 3000):
        raise ValueError("invalid_title")

    modules = payload.get("modules", [])
    if not isinstance(modules, list) or len(modules) > 24:
        raise ValueError("invalid_modules_list")

    clean_mods: List[str] = []
    for m in modules:
        if not isinstance(m, str) or not MODULE_ID_RE.match(m):
            raise ValueError("invalid_module_id")
        if m not in clean_mods:
            clean_mods.append(m)

    runtime = payload.get("runtime")
    if runtime is not None and (not isinstance(runtime, str) or len(runtime) > 64):
        raise ValueError("invalid_runtime")

    wing = payload.get("wing")
    if wing is not None and (not isinstance(wing, str) or not SLUG_RE.match(wing)):
        raise ValueError("invalid_wing")

    try:
        tenants_list, _ = _load_tenants(repo_root, data_root, tenant)
    except ValueError:
        raise LookupError("tenant_not_found")
    tenant_info = next((t for t in tenants_list if t["slug"] == tenant), None)
    if not tenant_info:
        raise LookupError("tenant_not_found")

    catalog, _ = _load_catalog(repo_root)
    cards = {c["id"]: c for c in catalog.get("cards", []) if isinstance(c, dict) and "id" in c}
    connectors = {c["id"]: c for c in catalog.get("connectors", []) if isinstance(c, dict) and "id" in c}

    fleet_nodes, _ = _load_fleet(repo_root, data_root)

    if wing is not None:
        wing_node = next((n for n in fleet_nodes if n.get("wing") == wing), None)
        if not wing_node:
            raise ValueError("unknown_wing")
    else:
        wing_node = None

    if runtime is not None:
        valid_runtimes = {a.get("id") for a in catalog.get("adapters", []) if isinstance(a, dict) and isinstance(a.get("id"), str)}
        valid_runtimes.update({"local-process", "container", "remote", "local"})
        for c in list(cards.values()) + list(connectors.values()):
            for r in c.get("runtimes", []):
                if isinstance(r, str):
                    valid_runtimes.add(r)
        for n in fleet_nodes:
            for r in n.get("profile", {}).get("runtimes", []):
                if isinstance(r, str):
                    valid_runtimes.add(r)
        if runtime not in valid_runtimes:
            raise ValueError("unknown_runtime")

    routing_data, _ = _load_routing(repo_root)
    matched_routes: List[Dict[str, Any]] = []
    seen_agent_hooks: Set[Tuple[str, str]] = set()
    title_lower = title.lower()

    for rule in routing_data.get("rules", []):
        for pattern in rule.get("globs", []):
            if fnmatch.fnmatch(title_lower, pattern.lower()):
                agent = str(rule.get("agent", "chief-of-staff"))
                hook = str(rule.get("hook", "evaluate"))
                key = (agent, hook)
                if key not in seen_agent_hooks:
                    seen_agent_hooks.add(key)
                    matched_routes.append({
                        "agent": agent,
                        "hook": hook,
                        "skills": rule.get("skills", []),
                        "source": rule.get("source", "routing"),
                    })
                break

    if not matched_routes:
        matched_routes.append({"agent": "chief-of-staff", "hook": "default-fallback",
                               "skills": [], "source": "escalation:no_match"})

    module_decisions: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []
    warnings: List[str] = []

    enabled_mods_set = set(tenant_info.get("enabledModules", []))

    for mod_id in clean_mods:
        card = cards.get(mod_id)
        connector = connectors.get(mod_id)
        info = card or connector

        if not info:
            module_decisions.append({
                "id": mod_id,
                "decision": "unknown",
                "reason": "Module not found in catalog",
            })
            steps.append({
                "id": f"step-{mod_id}",
                "label": f"Configure {mod_id}",
                "status": "held",
                "reason": "Unknown module catalog reference",
            })
            continue

        status_in_catalog = str(info.get("disposition", info.get("status", ""))).lower()
        risk = str(info.get("risk", "low")).lower()
        requires_approval = bool(info.get("requires_approval", False) or risk == "high" or str(info.get("approval", "")).lower() == "yes" or any(isinstance(c, dict) and (c.get("risk") == "high" or c.get("approval") == "yes") for c in info.get("capabilities", [])))

        # Hold/refuse always takes precedence and is refused even if enabled
        if status_in_catalog in ("hold", "refuse", "refused"):
            decision = "refused"
            reason = f"Module is flagged as {status_in_catalog}"
            st_status = "held"
        elif mod_id not in enabled_mods_set:
            decision = "disabled"
            reason = "Module not enabled for tenant"
            st_status = "held"
        elif wing_node and mod_id not in wing_node.get("profile", {}).get("modules", []) and mod_id not in wing_node.get("profile", {}).get("connectors", []):
            decision = "disabled"
            reason = f"Module not present on wing node {wing}"
            st_status = "held"
        elif runtime and info.get("runtimes") and runtime not in info.get("runtimes", []) and "any" not in info.get("runtimes", []):
            decision = "disabled"
            reason = f"Module does not support runtime {runtime}"
            st_status = "held"
        elif requires_approval:
            decision = "approval-required"
            reason = "High risk or approval-required module"
            st_status = "held"
        else:
            decision = "allowed"
            reason = "Enabled in tenant source; preview only"
            st_status = "proposed"

        module_decisions.append({
            "id": mod_id,
            "decision": decision,
            "reason": reason,
        })
        steps.append({
            "id": f"step-{mod_id}",
            "label": f"Execute {mod_id}",
            "status": st_status,
            "reason": reason,
        })

    digest_input = json.dumps({"tenant": tenant, "title": title, "modules": clean_mods, "runtime": runtime, "wing": wing}, sort_keys=True)
    plan_id = f"plan-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:16]}"

    return {
        "schema": "snowgloves.cockpit.plan.v1",
        "id": plan_id,
        "tenant": tenant,
        "title": title,
        "generatedAt": _now_iso(),
        "routes": matched_routes,
        "modules": module_decisions,
        "steps": steps,
        "executable": False,
        "warnings": warnings,
    }
