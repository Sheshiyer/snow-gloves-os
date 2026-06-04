import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.gtm import brand_to_gtm, load_brief, derive_brief

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


def _write_brief_md(d, arm="partner", status="draft"):
    p = d / f"brief-{arm}.md"
    p.write_text(
        "---\n"
        f"arm: {arm}\n"
        f"status: {status}\n"
        "companies_filters:\n  definition: consciousness tech\n  is_tech: true\n"
        "people_filters:\n  job_titles: [Founder]\n  people_per_company_limit: 2\n"
        "outreach_angle: peer\n"
        "fit_criteria:\n  - cross-tradition\n"
        "---\n\n# Brief\nbody\n"
    )
    return p


def test_load_brief_parses_frontmatter(tmp_path):
    b = load_brief(_write_brief_md(tmp_path, "partner", "draft"))
    assert b["arm"] == "partner" and b["status"] == "draft"
    assert b["companies_filters"]["definition"] == "consciousness tech"
    assert b["people_filters"]["job_titles"] == ["Founder"]


def test_derive_brief_writes_yaml_for_approved(tmp_path):
    import yaml
    md = _write_brief_md(tmp_path, "partner", "approved")
    out = tmp_path / "gtm"
    path = derive_brief(md, out)
    assert path == out / "brief-partner.yaml" and path.exists()
    derived = yaml.safe_load(path.read_text())
    assert derived["arm"] == "partner" and derived["status"] == "approved"
    assert derived["companies_filters"]["is_tech"] is True


def test_derive_brief_refuses_draft(tmp_path):
    out = tmp_path / "gtm"
    with pytest.raises(PermissionError):
        derive_brief(_write_brief_md(tmp_path, "partner", "draft"), out)
    assert not out.exists() or not list(out.glob("*.yaml"))
