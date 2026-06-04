import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.seed import load_targets


def test_load_targets_parses_frontmatter(tmp_path):
    tdir = tmp_path / "targets"
    tdir.mkdir()
    (tdir / "r-test.md").write_text(
        "---\n"
        "channel: reddit\n"
        "sub: TestSub\n"
        "best_thread_types:\n"
        "  - first type\n"
        "  - second type\n"
        "voice_notes: be rigorous\n"
        "---\n\n"
        "# Target: r/TestSub\nbody notes\n"
    )
    targets = load_targets(tmp_path)
    assert len(targets) == 1
    t = targets[0]
    assert t["sub"] == "TestSub"
    assert t["best_thread_types"] == ["first type", "second type"]
    assert t["voice_notes"] == "be rigorous"


def test_load_targets_ignores_non_md(tmp_path):
    (tmp_path / "targets").mkdir()
    (tmp_path / "targets" / "README.txt").write_text("not a target")
    assert load_targets(tmp_path) == []
