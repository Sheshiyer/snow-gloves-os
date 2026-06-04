"""tn-seed orchestration + queue writer (specs/003 — distribution OS).

Chains the Reddit reader -> fit scorer -> brief builder -> queue writer, writing
human-review-ready contribution briefs into the Content-Engine _distribution/queue/.
Paths and network are injectable so the chain is testable offline.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib.reddit import fetch_threads
from lib.score import score_thread
from lib.draft import build_brief

_FRONTMATTER_KEYS = ("channel", "sub", "source_url", "script", "script_name", "asset", "fit_score", "status")


def _slug(brief):
    m = re.search(r"/comments/([a-z0-9]+)", brief.get("source_url") or "")
    if m:
        return m.group(1)
    first = (brief.get("scaffold") or "thread").splitlines()[0]
    return re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")[:40] or "thread"


def _yaml_val(v):
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return repr(v)
    return v if re.fullmatch(r"[\w./:-]+", str(v)) else f'"{v}"'


def write_brief(brief, queue_root):
    """Write a brief as a review-ready markdown file -> queue_root/<sub>/<slug>.md."""
    sub = brief.get("sub") or "unknown"
    d = Path(queue_root) / sub
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_slug(brief)}.md"
    fm = "".join(f"{k}: {_yaml_val(brief.get(k))}\n" for k in _FRONTMATTER_KEYS)
    path.write_text(f"---\n{fm}---\n\n{brief.get('scaffold', '')}\n")
    return path


def run_seed(targets, queue_root, *, fetch_json, now=None, min_fit=0.5, sort="new", limit=25):
    """Per target: fetch -> score -> (skip low-fit / wrong-audience) -> brief -> queue.

    Returns the list of written paths.
    """
    written = []
    for target in targets:
        threads = fetch_threads(target["sub"], sort=sort, limit=limit, fetch_json=fetch_json, now=now)
        for th in threads:
            s = score_thread(th, target)
            if s["skip"] or s["fit"] < min_fit:
                continue
            written.append(write_brief(build_brief(th, target, s), queue_root))
    return written
