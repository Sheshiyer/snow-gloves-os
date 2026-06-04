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
import urllib.error
import urllib.request

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
