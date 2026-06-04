import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.score import score_thread

JUNG_TARGET = {
    "sub": "Jung",
    "best_thread_types": [
        "I understand my patterns but cannot change them",
        "Therapy gave me insight, now what?",
    ],
}


def _thread(title, body=""):
    return {"title": title, "body": body, "score": 10, "num_comments": 3, "age_hours": 6.0}


def test_high_fit_thread_scores_and_keeps():
    t = _thread(
        "I understand my patterns but cannot change them",
        "Therapy gave me so much insight but nothing changed. I've tried everything.",
    )
    r = score_thread(t, JUNG_TARGET)
    assert r["skip"] is False
    assert r["fit"] >= 0.6
    assert any("signal" in x for x in r["reasons"])
    assert any("thread-type" in x for x in r["reasons"])


def test_wrong_audience_is_skipped():
    t = _thread("Looks cool — how much does it cost?", "is there a free trial?")
    r = score_thread(t, JUNG_TARGET)
    assert r["skip"] is True
    assert r["fit"] == 0.0


def test_low_fit_thread_scores_low():
    t = _thread("Beautiful sunset over the mountains today", "just wanted to share this view")
    r = score_thread(t, JUNG_TARGET)
    assert r["skip"] is False
    assert r["fit"] < 0.3
