"""Thread fit scorer for tn-seed (specs/003 — distribution OS).

Triages normalized Reddit threads against Seeker-Simon frustration signals and a
target's best-thread-types, and drops wrong-audience tells. Pure + deterministic.
"""
from __future__ import annotations

import re

# Wrong-audience tells (the seeding guide's red flags) → skip outright.
WRONG_AUDIENCE = (
    "how much does it cost", "what's the price", "free trial", "discount",
    "promo code", "will this cure", "can i join your", "is there a coupon",
)

# Seeker-Simon frustration signals (the market signal per the persona / niche docs).
SEEKER_SIGNALS = (
    "understand my patterns", "can't change", "cannot change", "tried everything",
    "now what", "integrate", "integration", "plateau", "peak experience",
    "nothing changed", "still stuck", "still anxious", "insight but",
    "same patterns", "can't sit with",
)

_STOP = {"i", "me", "my", "the", "a", "an", "to", "of", "and", "but", "it",
         "them", "they", "is", "are", "this", "that", "now", "what"}


def _overlap(phrase, text):
    """Fraction of a phrase's significant words present in the text."""
    words = [w for w in re.findall(r"[a-z']+", phrase.lower()) if len(w) > 3 and w not in _STOP]
    if not words:
        return 0.0
    return sum(1 for w in words if w in text) / len(words)


def score_thread(thread, target=None):
    """Return {fit: 0.0-1.0, skip: bool, reasons: [...]} for a normalized thread."""
    text = f"{thread.get('title', '')} {thread.get('body', '')}".lower()

    for w in WRONG_AUDIENCE:
        if w in text:
            return {"fit": 0.0, "skip": True, "reasons": [f"wrong-audience: {w!r}"]}

    reasons = []
    signals = [s for s in SEEKER_SIGNALS if s in text]
    reasons += [f"signal: {s!r}" for s in signals]

    types = []
    for bt in (target or {}).get("best_thread_types", []):
        if _overlap(bt, text) >= 0.5:
            types.append(bt)
            reasons.append(f"thread-type: {bt!r}")

    fit = min(1.0, (0.5 if types else 0.0) + 0.15 * len(signals))
    return {"fit": round(fit, 2), "skip": False, "reasons": reasons}
