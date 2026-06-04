import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.gtm import brand_to_gtm

BRIEF = {
    "arm": "partner",
    "status": "approved",
    "companies_filters": {"definition": "consciousness tech", "is_tech": True, "criteria": ["can distribute"]},
    "people_filters": {"job_titles": ["Founder", "Head of Community"], "people_per_company_limit": 2},
}


def test_builds_search_payloads_for_approved_brief():
    calls = []

    def fake_call(method, path, body):
        calls.append((method, path, body))
        return {"results": []}

    brand_to_gtm(BRIEF, call=fake_call, page_size=10)

    comp = next(c for c in calls if c[1].endswith("/search/companies"))
    assert comp[0] == "POST"
    assert comp[2]["filters"] == BRIEF["companies_filters"]   # pinned: {filters, page, page_size}
    assert comp[2]["page_size"] == 10

    ppl = next(c for c in calls if c[1].endswith("/search/people"))
    assert ppl[2]["company_filters"] == BRIEF["companies_filters"]   # pinned: {company_filters, people_filters, …}
    assert ppl[2]["people_filters"] == BRIEF["people_filters"]


def test_refuses_unapproved_brief():
    calls = []
    draft = {**BRIEF, "status": "draft"}
    with pytest.raises(PermissionError):
        brand_to_gtm(draft, call=lambda *a: calls.append(a))
    assert calls == []  # never touched Explee — the spend gate held
