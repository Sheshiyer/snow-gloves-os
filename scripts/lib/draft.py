"""Contribution-brief builder for tn-seed (specs/003 — distribution OS).

Given a scored thread + target, picks a seeding script, names the Kha-Ba-La gap,
and assembles a human/Interpreter drafting BRIEF — deliberately NOT a finished,
paste-ready contribution (the brand forbids copy-paste; the human writes the words).
"""
from __future__ import annotations

SCRIPTS = {
    1: "building-something-related",
    2: "kha-ba-la-gap",
    3: "code-is-open",
    4: "sovereignty-over-dependency",
    5: "not-for-everyone",
}

_INTEGRATION = ("integrate", "integration", "ceremony", "peak experience", "plant medicine", "psychedelic", "retreat")
_INSIGHT = ("therapy", "insight", "patterns", "can't change", "cannot change", "shadow", "understand my")
_TECH = ("rust", "tui", "terminal", "open source", "github", "api", "command line")
_DEPENDENCY = ("guru", "dependency", "join the community", "subscription", "movement")
_OPTIMIZE = ("optimize", "productivity", "habit", "second brain", "gtd")


def pick_script(text):
    t = text.lower()
    if any(w in t for w in _INTEGRATION):
        return 1
    if any(w in t for w in _INSIGHT):
        return 2
    if any(w in t for w in _TECH):
        return 3
    if any(w in t for w in _DEPENDENCY):
        return 4
    return 5


def detect_gap(text):
    t = text.lower()
    if any(w in t for w in _INTEGRATION):
        return "explosive Kha (vision/opening), temporary Ba, zero La (no architecture for what opened)"
    if any(w in t for w in _INSIGHT):
        return "all Kha (insight), no Ba (embodiment), no La (the resistance that gives form)"
    if any(w in t for w in _OPTIMIZE):
        return "all La (structure), no Kha (who set the targets?), no Ba (what does the body know?)"
    return "(gap unclear — read the thread and name the imbalance honestly)"


def build_brief(thread, target=None, score=None):
    target = target or {}
    score = score or {}
    text = f"{thread.get('title', '')} {thread.get('body', '')}"
    script = pick_script(text)
    gap = detect_gap(text)
    voice = target.get("voice_notes", "grounded, rigorous, no guru energy")
    scaffold = (
        f'Thread: "{thread.get("title", "")}"\n'
        f"Detected gap: {gap}\n"
        f"Use seeding script {script} ({SCRIPTS[script]}).\n"
        f"Tailor a contribution to THIS specific thread (do not paste a template): name the gap where "
        f"it illuminates, add genuine value first, soft-reference a live product only if natural.\n"
        f"Voice: {voice}."
    )
    return {
        "channel": "reddit",
        "sub": thread.get("subreddit"),
        "source_url": thread.get("permalink"),
        "script": script,
        "script_name": SCRIPTS[script],
        "gap": gap,
        "asset": None,
        "fit_score": score.get("fit"),
        "status": "needs-review",
        "scaffold": scaffold,
    }
