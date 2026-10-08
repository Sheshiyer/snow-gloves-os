"""Prepare a secure, standalone Mac bundle for deployment and air-gapped run.

Copies an explicit allowlist of files, generates a cryptographically hashed
MANIFEST.json, includes standalone verification tooling (VERIFY.py), installation
guides (README-INSTALL.md), and provides atomic packaging guarantees.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Set, Tuple

MANIFEST_SCHEMA_VERSION = "snowgloves.mac-bundle.v1"
MAX_ALLOWED_FILES = 8192
MAX_ALLOWED_BYTES = 64 * 1024 * 1024  # 64 MiB
MAX_MANIFEST_BYTES = 1 * 1024 * 1024  # 1 MiB

ALLOWED_ROOT_DIRS = {
    "scripts",
    "apps",
    "catalog",
    "agents",
    "adapters",
    "connectors",
    "skills",
    "workflows",
    "docs",
}

ALLOWED_ROOT_FILES = {
    "README.md",
    "ISA.md",
    "VERSION",
    "requirements-ci.txt",
}

DISALLOWED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "private",
    "data",
    "tenants",
    "audit",
    "_audit",
    "nodes",
    "credentials",
    ".secrets",
}

DISALLOWED_FILE_NAMES = {
    "fleet.yaml",
    "nodes.yaml",
    "credentials.json",
    "credentials.yaml",
    ".env",
    ".env.local",
}

README_INSTALL_CONTENT = """# Mac Deployment Bundle

This bundle was created with deterministic content hashing and verified file integrity.

## Prerequisites
- Python 3.10+
- Node.js (v20.19+, v22.12+, or v24+) & npm

## Verification & Launch Tooling
Verify the bundle before installing dependencies:
```bash
# Check bundle integrity
python3 VERIFY.py check

```

## Installation & Setup
1. Initialize Python virtual environment and dependencies:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install PyYAML==6.0.3
```

2. Install UI dependencies (if building or running UI server):
```bash
npm --prefix apps/infra-block ci
```

3. Launch workspace:
```bash
.venv/bin/python scripts/ops_workspace.py check --data-root /absolute/path/to/privatecheckout
.venv/bin/python scripts/ops_workspace.py run --data-root /absolute/path/to/privatecheckout
```

Note: The private checkout data directory transfers separately. Built UI files are included.
"""


def compute_sha256(path: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _has_local_private_scope(data: object) -> bool:
    """Check recursively if any object has scope.mode == 'local-private'."""
    if isinstance(data, dict):
        scope = data.get("scope")
        if isinstance(scope, dict) and scope.get("mode") == "local-private":
            return True
        if data.get("scope.mode") == "local-private":
            return True
        for v in data.values():
            if _has_local_private_scope(v):
                return True
    elif isinstance(data, list):
        for item in data:
            if _has_local_private_scope(item):
                return True
    return False


def check_json_security(path: Path) -> bool:
    """Reject static JSON files containing scope.mode == 'local-private'."""
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        if _has_local_private_scope(data):
            return False
    except Exception:
        return False
    return True


def is_safe_allowlisted_relative_path(rel_str: str) -> bool:
    """Check if a POSIX relative path matches the explicit allowlist and exclusion rules."""
    if "\\" in rel_str or "\0" in rel_str:
        return False
    if rel_str.startswith("/") or rel_str.startswith("\\"):
        return False

    parts = PurePosixPath(rel_str).parts
    if not parts or any(p in {"..", ".", ""} for p in parts):
        return False

    for part in parts:
        if part.startswith("."):
            return False
        if part in DISALLOWED_DIR_NAMES:
            return False

    filename = parts[-1]
    if filename in DISALLOWED_FILE_NAMES or filename.endswith(".map"):
        return False

    # Exact root files
    if len(parts) == 1:
        return filename in ALLOWED_ROOT_FILES

    top = parts[0]
    if top not in ALLOWED_ROOT_DIRS:
        return False

    # scripts/**/*.py
    if top == "scripts":
        return filename.endswith(".py")

    # apps/infra-block
    if top == "apps":
        if len(parts) >= 2 and parts[1] == "infra-block":
            if len(parts) == 3:
                return filename in {
                    "index.html",
                    "package.json",
                    "package-lock.json",
                    "tsconfig.json",
                    "vite.config.ts",
                }
            if len(parts) >= 4:
                sub = parts[2]
                if sub == "src":
                    return filename.endswith((".ts", ".tsx", ".css", ".json"))
                if sub == "public":
                    return filename.endswith(".json")
                if sub == "dist":
                    return not filename.endswith(".map")
        return False

    # catalog
    if top == "catalog":
        if len(parts) == 2 and filename == "modules.json":
            return True
        if len(parts) >= 3 and parts[1] == "cards":
            return filename.endswith(".md")
        return False

    # agents
    if top == "agents":
        return filename.endswith((".md", ".yaml", ".yml"))

    # adapters
    if top == "adapters":
        return filename.endswith((".yaml", ".yml", ".md"))

    # connectors
    if top == "connectors":
        return filename.endswith((".yaml", ".yml", ".json", ".md"))

    # skills
    if top == "skills":
        return filename.endswith((".md", ".yaml", ".yml", ".json"))

    # workflows
    if top == "workflows":
        return filename.endswith((".yaml", ".yml"))

    # docs
    if top == "docs":
        return filename.endswith(".md")

    return False


def collect_allowlisted_files(repo_root: Path) -> List[Tuple[Path, str]]:
    """Scan only allowed branches of repo_root and return list of (absolute_path, relative_posix_str)."""
    collected: List[Tuple[Path, str]] = []
    seen_rel: Set[str] = set()
    total_bytes = 0

    # Check root files directly
    for root_file in sorted(ALLOWED_ROOT_FILES):
        src_file = repo_root / root_file
        if src_file.is_symlink() or not src_file.is_file():
            continue
        if is_safe_allowlisted_relative_path(root_file):
            if root_file.endswith(".json") and not check_json_security(src_file):
                raise ValueError(f"Static JSON security validation failed for {root_file}")
            file_size = src_file.stat().st_size
            total_bytes += file_size
            collected.append((src_file, root_file))
            seen_rel.add(root_file)

    # Scan only allowed root directories
    for top_dir_name in sorted(ALLOWED_ROOT_DIRS):
        top_dir = repo_root / top_dir_name
        if top_dir.is_symlink() or not top_dir.is_dir():
            continue

        for root_dir, dirs, files in os.walk(top_dir, followlinks=False):
            dirs[:] = [
                d for d in sorted(dirs)
                if not d.startswith(".")
                and d not in DISALLOWED_DIR_NAMES
                and not (Path(root_dir) / d).is_symlink()
            ]

            for f in sorted(files):
                abs_path = Path(root_dir) / f
                if abs_path.is_symlink() or not abs_path.is_file():
                    continue
                try:
                    rel_path = abs_path.relative_to(repo_root)
                except ValueError:
                    continue
                rel_posix = rel_path.as_posix()
                if rel_posix in seen_rel:
                    continue
                if is_safe_allowlisted_relative_path(rel_posix):
                    if rel_posix.endswith(".json") and (
                        "public" in rel_posix or "dist" in rel_posix or rel_posix.startswith("catalog/")
                    ):
                        if not check_json_security(abs_path):
                            raise ValueError(f"Static JSON security validation failed for {rel_posix}")
                    file_size = abs_path.stat().st_size
                    total_bytes += file_size
                    if total_bytes > MAX_ALLOWED_BYTES:
                        raise ValueError(f"Aggregate size exceeds limit of {MAX_ALLOWED_BYTES} bytes before copy")
                    collected.append((abs_path, rel_posix))
                    seen_rel.add(rel_posix)
                    if len(collected) > MAX_ALLOWED_FILES:
                        raise ValueError(f"File count exceeds limit of {MAX_ALLOWED_FILES} before copy")

    return sorted(collected, key=lambda x: x[1])


def get_verifier_source() -> str:
    """Return standalone VERIFY.py script content."""
    return r"""#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath

MANIFEST_FILENAME = "MANIFEST.json"
MAX_MANIFEST_BYTES = 1 * 1024 * 1024  # 1 MiB
MAX_ALLOWED_FILES = 8192
MAX_ALLOWED_BYTES = 64 * 1024 * 1024  # 64 MiB
ALLOWED_EXTRAS_DIRS = {".venv", "node_modules"}

def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def _is_hex64(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 64:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)

def verify_bundle(bundle_dir: Path) -> bool:
    if os.path.islink(bundle_dir):
        print(f"ERROR: Bundle directory itself is a symlink: {bundle_dir}", file=sys.stderr)
        return False

    # Check symlinks in bundle parent hierarchy
    curr = bundle_dir.parent
    while curr != curr.parent:
        if os.path.islink(curr):
            print(f"ERROR: Bundle ancestor is a symlink: {curr}", file=sys.stderr)
            return False
        curr = curr.parent

    bundle_dir = bundle_dir.resolve()
    manifest_path = bundle_dir / MANIFEST_FILENAME
    if os.path.islink(manifest_path) or not manifest_path.is_file():
        print(f"ERROR: Manifest not found or is a symlink: {manifest_path}", file=sys.stderr)
        return False

    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        print(f"ERROR: Manifest file exceeds max size {MAX_MANIFEST_BYTES} bytes", file=sys.stderr)
        return False

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Corrupted {MANIFEST_FILENAME}: {e}", file=sys.stderr)
        return False

    if manifest_data.get("schema") != "snowgloves.mac-bundle.v1":
        print("ERROR: Incompatible manifest schema.", file=sys.stderr)
        return False

    files_map = manifest_data.get("files", {})
    if not isinstance(files_map, dict):
        print("ERROR: Invalid files map in manifest.", file=sys.stderr)
        return False

    if len(files_map) > MAX_ALLOWED_FILES:
        print(f"ERROR: Manifest contains {len(files_map)} files (max {MAX_ALLOWED_FILES})", file=sys.stderr)
        return False

    total_size = 0
    missing_or_failed = False

    # Verify all files in manifest
    for rel_path_str, expected_hash in files_map.items():
        if "\\" in rel_path_str or "\0" in rel_path_str:
            print(f"ERROR: Invalid path format in manifest: {rel_path_str}", file=sys.stderr)
            return False
        if not _is_hex64(expected_hash):
            print(f"ERROR: Invalid hex64 sha256 hash in manifest for {rel_path_str}", file=sys.stderr)
            return False

        rel_pure = PurePosixPath(rel_path_str)
        if rel_pure.is_absolute() or any(p in {"..", ".", ""} for p in rel_pure.parts):
            print(f"ERROR: Unsafe relative path in manifest: {rel_path_str}", file=sys.stderr)
            return False

        target_file = bundle_dir.joinpath(*rel_pure.parts)
        if any(part.is_symlink() for part in (target_file, *target_file.parents)):
            print(f"ERROR: Symlink detected at {rel_path_str}", file=sys.stderr)
            missing_or_failed = True
            continue
        if not target_file.is_file():
            print(f"ERROR: Missing file: {rel_path_str}", file=sys.stderr)
            missing_or_failed = True
            continue

        file_size = target_file.stat().st_size
        total_size += file_size
        if total_size > MAX_ALLOWED_BYTES:
            print(f"ERROR: Aggregate bundle size exceeds {MAX_ALLOWED_BYTES} bytes", file=sys.stderr)
            return False

        actual_hash = compute_sha256(target_file)
        if actual_hash.lower() != expected_hash.lower():
            print(f"ERROR: Hash mismatch for {rel_path_str} (expected {expected_hash}, got {actual_hash})", file=sys.stderr)
            missing_or_failed = True

    if missing_or_failed:
        return False

    # Traverse bundle directory, rejecting all symlinks and untracked files
    for root_dir, dirs, files in os.walk(bundle_dir, followlinks=False):
        if os.path.islink(root_dir):
            print(f"ERROR: Symlink directory detected: {root_dir}", file=sys.stderr)
            return False

        # Check for symlink child directories
        for d in list(dirs):
            dir_path = Path(root_dir) / d
            if os.path.islink(dir_path) or dir_path.is_symlink():
                print(f"ERROR: Symlink directory found: {dir_path}", file=sys.stderr)
                return False

        # Filter allowed extra directories (only .venv and node_modules)
        dirs[:] = [d for d in dirs if d not in ALLOWED_EXTRAS_DIRS]
        rel_root = Path(root_dir).relative_to(bundle_dir)

        for f in files:
            file_path = Path(root_dir) / f
            if os.path.islink(file_path) or file_path.is_symlink():
                print(f"ERROR: Forbidden symlink found in bundle: {file_path}", file=sys.stderr)
                return False
            rel_f = (rel_root / f).as_posix() if str(rel_root) != "." else f
            if rel_f == MANIFEST_FILENAME:
                continue
            if rel_f not in files_map:
                print(f"ERROR: Untracked file found in bundle: {rel_f}", file=sys.stderr)
                return False

    print("SUCCESS: Bundle verification succeeded.")
    return True

def main() -> int:
    parser = argparse.ArgumentParser(description="Bundle verifier and runner launcher")
    parser.add_argument("subcommand", nargs="?", default="check", choices=["check", "run"], help="Subcommand to execute (check or run)")
    parser.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent, help="Bundle directory to verify")
    args = parser.parse_args()

    if not verify_bundle(args.dir):
        return 1
    if args.subcommand == "run":
        print("Launcher run check passed successfully.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""


def _validate_paths_before_resolve(repo_root: Path, output_dir: Path) -> None:
    """Perform security validations on path objects before symlink resolution."""
    # Reject original symlinks in repo_root or output_dir path objects before resolve
    if os.path.islink(repo_root):
        raise ValueError(f"Repo root path is a symlink: {repo_root}")
    if os.path.islink(output_dir):
        raise ValueError(f"Output directory path is a symlink: {output_dir}")

    # Check all parents before resolve (including dangling targets)
    curr_repo = repo_root
    while curr_repo != curr_repo.parent:
        if os.path.islink(curr_repo):
            raise ValueError(f"Repo root parent path is a symlink: {curr_repo}")
        curr_repo = curr_repo.parent

    curr_out = output_dir
    while curr_out != curr_out.parent:
        if os.path.islink(curr_out):
            raise ValueError(f"Output directory parent path is a symlink: {curr_out}")
        curr_out = curr_out.parent

    # Reject if output_dir already exists
    if output_dir.exists() or os.path.islink(output_dir):
        raise ValueError(f"Output directory already exists: {output_dir}")


def build_bundle(repo_root: Path, output_dir: Path) -> bool:
    """Build and assemble the standalone mac bundle at output_dir."""
    _validate_paths_before_resolve(repo_root, output_dir)

    repo_root_res = repo_root.resolve()
    output_parent_res = output_dir.parent.resolve()

    # Ensure output parent exists and is a directory
    if not output_parent_res.is_dir():
        raise ValueError(f"Output parent directory does not exist or is not a directory: {output_parent_res}")

    # Check if output is inside repo_root
    try:
        output_dir.resolve().relative_to(repo_root_res)
        raise ValueError(f"Output directory {output_dir} must not be inside repo root {repo_root}")
    except ValueError as e:
        if "must not be inside" in str(e):
            raise

    allowlisted = collect_allowlisted_files(repo_root_res)

    # Create a unique sibling temporary staging directory in output_dir.parent
    stage_dir_str = tempfile.mkdtemp(prefix=f".{output_dir.name}.stage_", dir=str(output_parent_res))
    stage_dir = Path(stage_dir_str)

    try:
        files_manifest: Dict[str, str] = {}
        total_bytes = 0

        for src_path, rel_posix in allowlisted:
            dest_path = stage_dir.joinpath(*PurePosixPath(rel_posix).parts)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path, follow_symlinks=False)
            f_hash = compute_sha256(dest_path)
            files_manifest[rel_posix] = f_hash
            total_bytes += dest_path.stat().st_size

        # Add README-INSTALL.md
        readme_path = stage_dir / "README-INSTALL.md"
        readme_path.write_text(README_INSTALL_CONTENT, encoding="utf-8")
        readme_hash = compute_sha256(readme_path)
        files_manifest["README-INSTALL.md"] = readme_hash
        total_bytes += readme_path.stat().st_size

        # Add VERIFY.py
        verify_path = stage_dir / "VERIFY.py"
        verify_path.write_text(get_verifier_source(), encoding="utf-8")
        verify_path.chmod(0o755)
        verify_hash = compute_sha256(verify_path)
        files_manifest["VERIFY.py"] = verify_hash
        total_bytes += verify_path.stat().st_size

        if len(files_manifest) > MAX_ALLOWED_FILES:
            raise ValueError(f"Bundle file count ({len(files_manifest)}) exceeds limit ({MAX_ALLOWED_FILES})")

        if total_bytes > MAX_ALLOWED_BYTES:
            raise ValueError(f"Bundle size ({total_bytes} bytes) exceeds limit ({MAX_ALLOWED_BYTES} bytes)")

        # Add MANIFEST.json
        manifest_path = stage_dir / "MANIFEST.json"
        manifest_payload = {
            "schema": MANIFEST_SCHEMA_VERSION,
            "physicalAcceptance": "unverified",
            "files": files_manifest,
        }
        manifest_text = json.dumps(manifest_payload, indent=2, sort_keys=True)
        if len(manifest_text.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ValueError(f"Generated manifest exceeds maximum allowed size of {MAX_MANIFEST_BYTES} bytes")
        manifest_path.write_text(manifest_text, encoding="utf-8")

        # Atomic rename
        stage_dir.rename(output_dir)
        return True
    except Exception:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def verify_existing_bundle(bundle_dir: Path) -> bool:
    """Execute verification on an existing bundle."""
    verifier_source = get_verifier_source()
    local_env: Dict = {"__name__": "bundle_verifier"}
    exec(verifier_source, local_env)
    return bool(local_env["verify_bundle"](bundle_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac Bundle Packaging and Verification CLI")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent, help="Root of source repository")
    parser.add_argument("--output", type=Path, default=None, help="Explicit non-existing output directory outside repo")
    parser.add_argument("--verify", type=Path, default=None, help="Path to existing bundle to verify")

    args = parser.parse_args()

    if args.verify:
        if not verify_existing_bundle(args.verify):
            print("Bundle verification failed!", file=sys.stderr)
            return 1
        print("Bundle verification passed.")
        return 0

    if not args.output:
        print("ERROR: Either --output <path> or --verify <bundle_path> is required.", file=sys.stderr)
        return 2

    try:
        build_bundle(args.repo_root, args.output)
        print(f"Successfully assembled mac bundle at {args.output}")
        return 0
    except Exception as exc:
        print(f"Bundle build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
