"""Anonymous Reddit reader for tn-seed (specs/003 — distribution OS).

Fetches public Reddit listing JSON (no auth) and normalizes posts into thread
dicts. Network I/O is injectable (`fetch_json`) so the logic is testable offline;
the default fetcher does an anonymous GET with a descriptive User-Agent + 429 backoff.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "tn-seed/0.1 (snow-gloves-os community-seeding; +https://tryambakam.space)"
_BASE = "https://www.reddit.com"


def normalize_listing(listing, now=None):
    """Extract t3 posts from a Reddit listing into normalized thread dicts."""
    now = time.time() if now is None else now
    out = []
    for child in (listing.get("data", {}) or {}).get("children", []) or []:
        if child.get("kind") != "t3":  # posts only (skip comments / other kinds)
            continue
        d = child.get("data", {}) or {}
        created = float(d.get("created_utc") or 0.0)
        out.append({
            "id": d.get("id"),
            "subreddit": d.get("subreddit"),
            "title": d.get("title", ""),
            "body": d.get("selftext", ""),
            "score": int(d.get("score", 0) or 0),
            "num_comments": int(d.get("num_comments", 0) or 0),
            "permalink": _BASE + (d.get("permalink") or ""),
            "url": d.get("url"),
            "created_utc": created,
            "age_hours": round(max(0.0, (now - created) / 3600.0), 1),
            "stickied": bool(d.get("stickied", False)),
        })
    return out


def fetch_threads(subreddit, sort="new", limit=25, period="week", *, fetch_json=None, now=None):
    """Fetch + normalize posts from /r/<sub>/<sort>.json (anonymous)."""
    fetch_json = fetch_json or _default_fetch_json
    sub = subreddit.strip().removeprefix("r/").strip("/")
    url = f"{_BASE}/r/{sub}/{sort}.json?limit={int(limit)}"
    if sort == "top":
        url += f"&t={period}"
    return normalize_listing(fetch_json(url), now=now)


def _default_fetch_json(url, *, retries=3, timeout=15):
    """Anonymous GET → parsed JSON, with descriptive User-Agent and 429 backoff."""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    if last:
        raise last
    raise RuntimeError("fetch failed")
