import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.draft import build_brief


def _thread(title, body="", sub="Jung", pid="abc"):
    return {
        "title": title,
        "body": body,
        "subreddit": sub,
        "permalink": f"https://www.reddit.com/r/{sub}/comments/{pid}/x/",
        "score": 10, "num_comments": 4, "age_hours": 6.0,
    }


TARGET = {"sub": "Jung", "voice_notes": "rigorous, no guru energy"}


def test_insight_thread_uses_kha_ba_la_gap_script():
    t = _thread("I understand my patterns but cannot change them",
                "Therapy gave me insight. Nothing changed.")
    b = build_brief(t, TARGET, {"fit": 0.9, "skip": False, "reasons": []})
    assert b["script"] == 2
    assert "Kha" in b["gap"]
    assert b["status"] == "needs-review"
    assert b["sub"] == "Jung"
    assert b["source_url"] == t["permalink"]
    assert b["fit_score"] == 0.9
    assert "understand my patterns" in b["scaffold"].lower()


def test_integration_thread_uses_building_script():
    t = _thread("How do I integrate my ceremony experience?", "the peak faded",
                sub="RationalPsychonaut")
    b = build_brief(t, {"sub": "RationalPsychonaut"}, {"fit": 0.8, "skip": False, "reasons": []})
    assert b["script"] == 1
    assert "explosive Kha" in b["gap"]


def test_brief_is_a_brief_not_a_paste_block():
    t = _thread("Therapy insight but can't change")
    b = build_brief(t, TARGET, {"fit": 0.7, "skip": False, "reasons": []})
    assert b["channel"] == "reddit"
    assert "tailor" in b["scaffold"].lower()  # instructs tailoring, not pasting
