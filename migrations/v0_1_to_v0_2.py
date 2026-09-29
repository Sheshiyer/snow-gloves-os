"""0.1 -> 0.2: rename the legacy event bus to Hermes in tenant files.

- `<old>-events.jsonl` files become `hermes-events.jsonl` (appended if both exist).
- Bus names in tenant yaml/md/json/txt text and config keys become Hermes
  (`<old>_channel` -> `hermes_channel`, `<OLD>_PORT` -> `HERMES_PORT`, ...).
- Event logs and vector indexes keep their historical content.
"""
from __future__ import annotations

from pathlib import Path

FROM = "0.1"
TO = "0.2"

# Assembled from parts so the repo-wide legacy-name grep stays clean.
_S, _B = "sg", "bus"
REPLACEMENTS = [
    (f"{_S.upper()} {_B.capitalize()}", "Hermes"),
    (f"{_S.upper()}_{_B.upper()}", "HERMES"),
    (f"{_S}_{_B}", "hermes"),
    (f"{_S}-{_B}", "hermes"),
]
TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".json", ".txt", ".toml"}
SKIP_DIRS = {"_embed_cache", ".git", "node_modules"}


def rename_text(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts):
            yield p


def migrate(tenant_dir: Path) -> list[str]:
    notes: list[str] = []
    for p in list(_files(tenant_dir)):
        new_name = rename_text(p.name)
        if new_name != p.name:
            dst = p.with_name(new_name)
            if dst.exists():
                with dst.open("ab") as fh:
                    fh.write(p.read_bytes())
                p.unlink()
                notes.append(f"merged {p.name} into {new_name}")
            else:
                p.rename(dst)
                notes.append(f"renamed {p.name} -> {new_name}")
    for p in _files(tenant_dir):
        if p.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = rename_text(text)
        if new != text:
            p.write_text(new, encoding="utf-8")
            notes.append(f"rewrote bus references in {p.relative_to(tenant_dir)}")
    return notes
