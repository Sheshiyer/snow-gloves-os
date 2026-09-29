import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Assembled from parts so this file does not match itself.
LEGACY = ("sg" + "_bus", "SG" + " Bus")
SKIP_DIRS = {".git", "node_modules", "target", "__pycache__", ".pytest_cache"}


def test_no_legacy_bus_names():
    hits = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".bak-")]
        for name in filenames:
            p = Path(dirpath, name)
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(word in text for word in LEGACY):
                hits.append(p.relative_to(REPO).as_posix())
    assert hits == []
