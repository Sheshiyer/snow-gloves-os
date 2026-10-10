import json, re, hashlib
from itertools import islice
from pathlib import Path

MAX_JSON_BYTES, MAX_HASH_BYTES, MAX_HASH_COUNT, MAX_RECORDS = 131072, 500000, 128, 128
CANONICAL_CONTEXT = {"company.md", "customer.md", "offer.md", "open-questions.md", "owner.md", "proof.md", "voice.md"}
SLUG_RE, HEX_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$"), re.compile(r"^[0-9a-f]{64}$")
SECRET_RE = re.compile(r"(?i)(?:bearer\s+[^\s,;]+|(?:token|secret|api[_-]?key|password|credential)[=:\s]+[^\s,;]+)")

def _is_safe(p: Path, root: Path) -> bool:
    try:
        if any(c.is_symlink() for c in (p, *p.parents)):
            return False
        res, r_res = p.resolve(), root.resolve()
        return res == r_res or r_res in res.parents
    except OSError:
        return False

def _load_json(p: Path):
    try:
        if not _is_safe(p, p.parent if p.is_file() else p) or not p.is_file():
            return None
        with open(p, "rb") as f:
            raw = f.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                return None
            return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

def _hash_file(p: Path, budget: list[int]) -> str | None:
    if budget[0] >= MAX_HASH_COUNT:
        return None
    try:
        if not _is_safe(p, p.parent) or not p.is_file():
            return None
        h = hashlib.sha256()
        total = 0
        with open(p, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_HASH_BYTES:
                    return None
                h.update(chunk)
        budget[0] += 1
        return h.hexdigest()
    except OSError:
        return None

def _sanitize_tenant_rel(raw: str, tenant_slug: str) -> Path | None:
    if not isinstance(raw, str) or "\0" in raw or "\\" in raw:
        return None
    parts = [p for p in raw.split("/") if p and p != "."]
    if ".." in parts or parts.count("tenants") != 1:
        return None
    idx = parts.index("tenants")
    if not raw.startswith("/") and idx != 0:
        return None
    if not (len(parts) > idx + 2 and parts[idx + 1] == tenant_slug):
        return None
    rem = parts[idx + 2:]
    if not rem or any(c in rem for c in (".", "..")):
        return None
    return Path(*rem)

def _clean_name(val: object) -> str:
    s = val if isinstance(val, str) else ""
    s = SECRET_RE.sub("[REDACTED]", s)
    return s[:128]

def brand_summary(data_root: Path, tenant_dir: Path, source_data: dict | list | None) -> dict:
    if not isinstance(data_root, Path) or not isinstance(tenant_dir, Path):
        raise ValueError("Invalid paths")
    if any(c.is_symlink() for c in (data_root, *data_root.parents)) or any(c.is_symlink() for c in (tenant_dir, *tenant_dir.parents)):
        raise ValueError("Symlinks rejected")
    slug = tenant_dir.name
    if not SLUG_RE.match(slug) or len(slug) > 64 or tenant_dir != (data_root / "tenants" / slug):
        raise ValueError("Invalid tenant path structure")
    if not _is_safe(tenant_dir, data_root):
        raise ValueError("Unsafe tenant dir")

    # 1. Context Files
    ctx_dir = tenant_dir / "context"
    ctx_cnt = 0
    if _is_safe(ctx_dir, tenant_dir) and ctx_dir.is_dir():
        for f in CANONICAL_CONTEXT:
            cp = ctx_dir / f
            if cp.is_file() and _is_safe(cp, ctx_dir):
                ctx_cnt += 1

    # 2. Sources
    reg_src, adm_src = 0, 0
    s_list = source_data.get("sources", []) if isinstance(source_data, dict) and source_data.get("tenant") == slug else (source_data if isinstance(source_data, list) else [])
    if isinstance(s_list, list):
        for s in s_list[:MAX_RECORDS]:
            if isinstance(s, dict) and isinstance(s.get("id"), str) and isinstance(s.get("type"), str):
                reg_src += 1
                if s.get("ingest") is True:
                    adm_src += 1

    # 3. Ingest Plan Files
    plan_f, pres_f, miss_f, rej_f = 0, 0, 0, 0
    plan_data = _load_json(tenant_dir / "ingest-plan.json")
    if isinstance(plan_data, dict) and plan_data.get("tenant") == slug and isinstance(plan_data.get("files"), list):
        for item in plan_data["files"][:MAX_RECORDS]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                rej_f += 1
                continue
            rel = _sanitize_tenant_rel(item["path"], slug)
            if not rel:
                rej_f += 1
                continue
            target = tenant_dir / rel
            if not _is_safe(target, tenant_dir):
                rej_f += 1
                continue
            plan_f += 1
            if target.is_file():
                pres_f += 1
            else:
                miss_f += 1

    # 4. Research Provenance
    r_files, r_ver, r_miss, r_drift, r_rej = 0, 0, 0, 0, 0
    res_budget = [0]
    wiki_res = tenant_dir / "wiki" / "research"
    if wiki_res.is_dir() and _is_safe(wiki_res, tenant_dir):
        prov_list = []
        try:
            prov_list = sorted(islice((p for p in wiki_res.glob("*/provenance.json") if _is_safe(p, tenant_dir)), MAX_RECORDS))
        except OSError:
            pass
        glob_records = 0
        for prov in prov_list[:MAX_RECORDS]:
            p_json = _load_json(prov)
            if not isinstance(p_json, dict) or p_json.get("tenant") != slug or not isinstance(p_json.get("files"), list):
                r_rej += 1
                continue
            for rf in p_json["files"]:
                if glob_records >= MAX_RECORDS:
                    break
                glob_records += 1
                r_files += 1
                if not isinstance(rf, dict):
                    r_rej += 1
                    continue
                snap, sha = rf.get("snapshot"), rf.get("sha256")
                if not isinstance(snap, str) or not isinstance(sha, str) or not HEX_RE.match(sha):
                    r_rej += 1
                    continue
                rel = _sanitize_tenant_rel(snap, slug)
                if not rel:
                    r_rej += 1
                    continue
                target = tenant_dir / rel
                if not _is_safe(target, tenant_dir):
                    r_rej += 1
                    continue
                if not target.exists():
                    r_miss += 1
                else:
                    h = _hash_file(target, res_budget)
                    if h is None:
                        r_rej += 1
                    elif h == sha:
                        r_ver += 1
                    else:
                        r_drift += 1

    prov_status = "unavailable"
    if r_files > 0:
        if r_ver == r_files and r_drift == 0 and r_miss == 0 and r_rej == 0:
            prov_status = "verified"
        elif r_drift > 0:
            prov_status = "drift"
        elif r_miss > 0:
            prov_status = "missing"

    out = {
        "knowledge": {
            "registeredSources": reg_src, "admittedSources": adm_src,
            "contextFiles": ctx_cnt, "plannedFiles": plan_f, "presentFiles": pres_f,
            "missingFiles": miss_f, "rejectedFiles": rej_f, "researchFiles": r_files,
            "researchVerified": r_ver, "researchMissing": r_miss, "researchDrift": r_drift,
            "researchRejected": r_rej, "status": "source-plan-only", "provenanceStatus": prov_status
        }
    }

    # 5. Organization Desk Templates
    allowed_desks = []
    org_data = _load_json(data_root / "specs" / "006-editorial-steward-integration" / "organization.json")
    if isinstance(org_data, dict) and isinstance(org_data.get("desk_templates"), list):
        for dt in org_data["desk_templates"][:MAX_RECORDS]:
            if isinstance(dt, dict) and dt.get("status") == "proposed" and dt.get("id") in ("editorial", "creative-production", "delivery", "growth"):
                allowed_desks.append(dt["id"])

    # 6. Planning
    pmap = _load_json(data_root / "specs" / "006-editorial-steward-integration" / "portfolio-map-proposal.json")
    if isinstance(pmap, dict):
        matched, rel, parent = False, None, None
        p_obj = pmap.get("portfolio") if isinstance(pmap.get("portfolio"), dict) else {}
        p_id = p_obj.get("id") if isinstance(p_obj.get("id"), str) and SLUG_RE.match(p_obj.get("id")) else None
        valid_parents = {p_id} if p_id else set()
        branches = pmap.get("branches", []) if isinstance(pmap.get("branches"), list) else []
        for b in branches[:MAX_RECORDS]:
            if isinstance(b, dict) and isinstance(b.get("id"), str) and SLUG_RE.match(b["id"]):
                valid_parents.add(b["id"])
        if p_id == slug:
            matched, rel, parent = True, "portfolio", None
        else:
            for b in branches[:MAX_RECORDS]:
                if isinstance(b, dict) and b.get("id") == slug:
                    matched = True
                    rel = b.get("relationship") if b.get("relationship") in ("operating_branch", "product_wing") else "operating_branch"
                    raw_par = b.get("parent")
                    parent = raw_par if (isinstance(raw_par, str) and SLUG_RE.match(raw_par) and raw_par in valid_parents) else None
                    break
        if matched:
            projs = []
            for p in (pmap.get("projects", []) if isinstance(pmap.get("projects"), list) else [])[:MAX_RECORDS]:
                if isinstance(p, dict) and p.get("parent") == slug and isinstance(p.get("id"), str) and SLUG_RE.match(p["id"]) and len(p["id"]) <= 64:
                    projs.append({"id": p["id"], "name": _clean_name(p.get("name")), "status": "planning_not_provisioned"})
            flows = []
            for f in (pmap.get("cross_brand_flows", []) if isinstance(pmap.get("cross_brand_flows"), list) else [])[:MAX_RECORDS]:
                if isinstance(f, dict) and isinstance(f.get("participants"), list) and slug in f["participants"] and isinstance(f.get("id"), str) and SLUG_RE.match(f["id"]) and len(f["id"]) <= 64:
                    flows.append({"id": f["id"], "status": "proposed_not_approved"})
            out["planning"] = {
                "parent": parent, "relationship": rel, "authority": "planning-only",
                "status": "planning_not_provisioned", "projects": projs,
                "desks": allowed_desks, "flows": flows, "sources": [f"data:tenant:{slug}:planning"]
            }
    return out
