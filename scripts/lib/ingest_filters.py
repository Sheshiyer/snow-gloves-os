"""Glob and size filters for tenant ingest plans."""
from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath


def _posix_rel(path: Path, root: Path) -> str:
    if path == root and path.is_file():
        return path.name
    return PurePosixPath(path.relative_to(root)).as_posix()


def _glob_match(rel: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/")
    rel = rel.replace("\\", "/")
    if "**" in pattern:
        tail = pattern.split("**", 1)[-1].lstrip("/")
        if tail and (fnmatch.fnmatch(rel, tail) or fnmatch.fnmatch(Path(rel).name, tail)):
            return True
        collapsed = pattern.replace("**/", "").replace("**", "*")
        if fnmatch.fnmatch(rel, collapsed):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
    return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern)


def excluded_by_glob(rel: str, exclude_glob: list[str] | None) -> str | None:
    if not exclude_glob:
        return None
    parts = PurePosixPath(rel).parts
    for pat in exclude_glob:
        if _glob_match(rel, pat):
            return f"exclude_glob:{pat}"
        if "node_modules" in pat and "node_modules" in parts:
            return f"exclude_glob:{pat}"
        if ".git" in pat and ".git" in parts:
            return f"exclude_glob:{pat}"
    return None


def included_by_glob(rel: str, include_glob: list[str] | None) -> bool:
    if not include_glob:
        return True
    return any(_glob_match(rel, pat) for pat in include_glob)


def iter_ingest_files(
    root: Path,
    include_glob: list[str] | None = None,
    exclude_glob: list[str] | None = None,
    max_file_bytes: int | None = None,
) -> tuple[list[dict], list[dict]]:
    files: list[dict] = []
    skipped: list[dict] = []

    def consider(f: Path) -> None:
        if not f.is_file():
            return
        rel_parts = f.relative_to(root).parts if root.is_dir() and f != root else (f.name,)
        if any(part.startswith(".") for part in rel_parts):
            skipped.append({"path": str(f), "reason": "dot_path"})
            return
        try:
            size = f.stat().st_size
        except OSError as e:
            skipped.append({"path": str(f), "reason": f"stat_error:{e}"})
            return
        rel = _posix_rel(f, root) if root.is_dir() else f.name
        ex = excluded_by_glob(rel, exclude_glob)
        if ex:
            skipped.append({"path": str(f), "reason": ex})
            return
        if not included_by_glob(rel, include_glob):
            skipped.append({"path": str(f), "reason": "include_glob:no_match"})
            return
        if max_file_bytes is not None and size > max_file_bytes:
            skipped.append({"path": str(f), "reason": f"max_file_bytes:{size}>{max_file_bytes}"})
            return
        files.append({"path": str(f), "size": size})

    if root.is_file():
        consider(root)
    else:
        for f in root.rglob("*"):
            consider(f)

    return files, skipped
