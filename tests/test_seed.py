import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.draft import build_brief
from lib.seed import write_brief, run_seed

TARGET = {
    "sub": "Jung",
    "best_thread_types": ["I understand my patterns but cannot change them"],
    "voice_notes": "rigorous",
}


def _thread(title, body="", sub="Jung", pid="abc123"):
    return {
        "title": title, "body": body, "subreddit": sub,
        "permalink": f"https://www.reddit.com/r/{sub}/comments/{pid}/x/",
        "score": 10, "num_comments": 4, "age_hours": 6.0, "created_utc": 1_700_000_000.0,
    }


def test_write_brief_creates_file_with_frontmatter(tmp_path):
    th = _thread("I understand my patterns but cannot change them", "tried everything, nothing changed")
    brief = build_brief(th, TARGET, {"fit": 0.9, "skip": False, "reasons": []})
    path = write_brief(brief, tmp_path)
    assert path == tmp_path / "Jung" / "abc123.md"
    assert path.exists()
    text = path.read_text()
    assert text.startswith("---")
    assert "status: needs-review" in text
    assert "fit_score: 0.9" in text
    assert "https://www.reddit.com/r/Jung/comments/abc123/x/" in text
    assert "Tailor" in text  # scaffold body present


def test_run_seed_queues_high_fit_and_skips_others(tmp_path):
    listing = {"data": {"children": [
        {"kind": "t3", "data": {
            "id": "good1", "subreddit": "Jung",
            "title": "I understand my patterns but cannot change them",
            "selftext": "therapy gave insight, nothing changed, tried everything",
            "score": 20, "num_comments": 5, "permalink": "/r/Jung/comments/good1/x/",
            "created_utc": 1_700_000_000.0,
        }},
        {"kind": "t3", "data": {
            "id": "bad1", "subreddit": "Jung",
            "title": "how much does it cost?", "selftext": "free trial?",
            "score": 1, "num_comments": 0, "permalink": "/r/Jung/comments/bad1/x/",
            "created_utc": 1_700_000_000.0,
        }},
    ]}}
    written = run_seed([TARGET], tmp_path, fetch_json=lambda url: listing, now=1_700_000_000.0 + 3600)
    assert sorted(p.name for p in written) == ["good1.md"]        # high-fit queued
    assert not (tmp_path / "Jung" / "bad1.md").exists()           # wrong-audience skipped
