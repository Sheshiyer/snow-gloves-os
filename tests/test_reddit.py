import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.reddit import normalize_listing, fetch_threads

T0 = 1_700_000_000.0

SAMPLE = {
    "kind": "Listing",
    "data": {
        "children": [
            {"kind": "t3", "data": {
                "id": "abc123",
                "subreddit": "Jung",
                "title": "I understand my patterns but cannot change them",
                "selftext": "Therapy gave me insight. Nothing changed.",
                "score": 42,
                "num_comments": 7,
                "permalink": "/r/Jung/comments/abc123/i_understand/",
                "url": "https://example.com/x",
                "created_utc": T0,
                "stickied": False,
            }},
            {"kind": "t1", "data": {"id": "comment1", "body": "a comment, not a post"}},
        ]
    },
}


def test_normalize_extracts_fields():
    threads = normalize_listing(SAMPLE, now=T0 + 3600 * 5)  # 5h later
    assert len(threads) == 1  # only the t3 post
    t = threads[0]
    assert t["id"] == "abc123"
    assert t["subreddit"] == "Jung"
    assert t["body"] == "Therapy gave me insight. Nothing changed."
    assert t["score"] == 42 and t["num_comments"] == 7
    assert t["permalink"] == "https://www.reddit.com/r/Jung/comments/abc123/i_understand/"
    assert t["age_hours"] == 5.0


def test_normalize_skips_non_posts():
    threads = normalize_listing(SAMPLE, now=T0)
    assert [t["id"] for t in threads] == ["abc123"]  # t1 comment skipped


def test_fetch_threads_builds_url_and_normalizes():
    seen = {}

    def fake_fetch(url):
        seen["url"] = url
        return SAMPLE

    threads = fetch_threads("r/Jung", sort="new", limit=25, fetch_json=fake_fetch, now=T0)
    assert seen["url"] == "https://www.reddit.com/r/Jung/new.json?limit=25"
    assert len(threads) == 1 and threads[0]["subreddit"] == "Jung"


def test_fetch_top_includes_period():
    seen = {}
    fetch_threads(
        "Jung", sort="top", limit=10, period="week",
        fetch_json=lambda u: (seen.__setitem__("url", u) or SAMPLE), now=T0,
    )
    assert seen["url"] == "https://www.reddit.com/r/Jung/top.json?limit=10&t=week"
