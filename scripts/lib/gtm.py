"""Brand-enriched AutoGTM executor (specs/004).

Takes an APPROVED Brand GTM Brief (a populated PublicCompaniesFilters + PublicPeopleFilters,
synthesized from brand-docs) and runs Explee search via the explee-proxy connector. Deterministic;
the network call is injectable so it's testable offline. Paid ops require an approved Brief.

Explee request bodies are pinned from the live OpenAPI spec:
  POST /search/companies  {filters: PublicCompaniesFilters, page, page_size}
  POST /search/people     {company_filters: PublicCompaniesFilters, people_filters: PublicPeopleFilters, page, page_size}
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import yaml

PROXY = os.environ.get("EXPLEE_PROXY_URL", "https://explee-proxy.sheshnarayan-iyer.workers.dev")
COMPANIES = "/public/api/v1/search/companies"
PEOPLE = "/public/api/v1/search/people"


def brand_to_gtm(brief, *, call=None, page_size=10):
    """Run AutoGTM from an APPROVED Brief. Returns {arm, companies, people}.

    `call(method, path, body) -> dict` is injectable (default posts to the explee-proxy).
    Raises PermissionError if the Brief is not approved (the spend gate — constitution #4).
    """
    if (brief or {}).get("status") != "approved":
        raise PermissionError("Brief not approved — refusing to drive paid Explee ops (constitution #4)")
    call = call or _default_call
    cf = brief.get("companies_filters") or {}
    pf = brief.get("people_filters") or {}
    companies = call("POST", COMPANIES, {"filters": cf, "page": 1, "page_size": page_size})
    people = call("POST", PEOPLE, {"company_filters": cf, "people_filters": pf, "page": 1, "page_size": page_size})
    return {"arm": brief.get("arm"), "companies": companies, "people": people}


def load_brief(path):
    """Parse a Brand GTM Brief markdown file → dict (its frontmatter)."""
    text = Path(path).read_text()
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    return (yaml.safe_load(parts[1]) if len(parts) >= 3 else {}) or {}


def derive_brief(md_path, tenant_gtm_dir):
    """Derive the executable tenant yaml from an APPROVED Brief .md. Refuses drafts (the spend gate)."""
    brief = load_brief(md_path)
    if brief.get("status") != "approved":
        raise PermissionError("Brief not approved — refusing to derive an executable payload (spend gate)")
    out = Path(tenant_gtm_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"brief-{brief.get('arm', 'unknown')}.yaml"
    path.write_text(yaml.safe_dump(brief, sort_keys=False))
    return path


def _sig_words(phrase):
    """Significant (len>4) lowercase words of a fit-criterion phrase."""
    return [w for w in re.findall(r"[a-z]+", str(phrase).lower()) if len(w) > 4]


def score_fit(candidate, brief):
    """Re-score one raw Explee candidate against the Brief's fit_criteria (brand/positioning fit).

    Pure + deterministic — the brand-fit pass that re-ranks raw firmographic results. A criterion is
    met when >= half its significant words appear in the candidate's text. Returns {fit: 0..1, reasons}.
    """
    text = " ".join(
        str(candidate.get(k, "")) for k in ("name", "title", "description", "summary", "definition", "industry")
    ).lower()
    crits = (brief or {}).get("fit_criteria") or []
    matched = []
    for c in crits:
        words = _sig_words(c)
        if words and sum(1 for w in words if w in text) / len(words) >= 0.5:
            matched.append(c)
    fit = round(len(matched) / len(crits), 2) if crits else 0.0
    return {"fit": fit, "reasons": [f"fit: {m!r}" for m in matched]}


def rank_candidates(candidates, brief):
    """Re-rank Explee candidates by brand fit (highest first); annotates each with fit + reasons."""
    scored = [{**c, **score_fit(c, brief)} for c in candidates]
    return sorted(scored, key=lambda x: x["fit"], reverse=True)


def _default_call(method, path, body, *, timeout=30):
    """POST to the explee-proxy (needs the gate token in EXPLEE_PROXY_TOKEN)."""
    token = os.environ.get("EXPLEE_PROXY_TOKEN")
    if not token:
        raise RuntimeError("EXPLEE_PROXY_TOKEN not set — cannot reach the explee-proxy")
    req = urllib.request.Request(
        PROXY + path,
        data=json.dumps(body).encode(),
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Proxy-Token": token},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))
