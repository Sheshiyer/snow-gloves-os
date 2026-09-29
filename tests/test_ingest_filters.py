import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.ingest_filters import iter_ingest_files


def test_include_glob_md_only(tmp_path):
    (tmp_path / "a.md").write_text("hello")
    (tmp_path / "b.txt").write_text("skip")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("nested")

    files, skipped = iter_ingest_files(tmp_path, include_glob=["**/*.md"])
    paths = {Path(f["path"]).name for f in files}
    assert paths == {"a.md", "c.md"}
    assert any(s["reason"] == "include_glob:no_match" for s in skipped)


def test_max_file_bytes_skip(tmp_path):
    big = tmp_path / "big.md"
    big.write_text("x" * 200)
    small = tmp_path / "small.md"
    small.write_text("ok")

    files, skipped = iter_ingest_files(tmp_path, include_glob=["**/*.md"], max_file_bytes=100)
    assert len(files) == 1
    assert Path(files[0]["path"]).name == "small.md"
    assert any("max_file_bytes" in s["reason"] for s in skipped)


def test_exclude_node_modules(tmp_path):
    nm = tmp_path / "pkg" / "node_modules" / "x"
    nm.mkdir(parents=True)
    (nm / "readme.md").write_text("skip")
    (tmp_path / "ok.md").write_text("keep")

    files, _skipped = iter_ingest_files(
        tmp_path,
        include_glob=["**/*.md"],
        exclude_glob=["**/node_modules/**"],
    )
    assert len(files) == 1
    assert Path(files[0]["path"]).name == "ok.md"
