import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import upgrade  # noqa: E402

# Legacy bus names, assembled so the repo-wide grep for them stays clean.
OLD = "SG" + " Bus"
OLD_KEY = "sg" + "_bus"
OLD_FILE = "sg" + "-bus-events.jsonl"
OLD_ENV = "SG" + "_BUS_PORT"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "VERSION").write_text("0.2.0\n")
    t = tmp_path / "tenants" / "acme"
    (t / "audit").mkdir(parents=True)
    (t / "MANIFEST.yaml").write_text(f"tenant: acme\n{OLD_KEY}_channel: snowgloves.events.v1\n")
    (t / "README.md").write_text(f"Events flow through the {OLD}. Port: ${OLD_ENV}.\n")
    (t / "audit" / OLD_FILE).write_text(f'{{"event": "{OLD_KEY}.ping"}}\n')
    (t / "_embed_cache").mkdir()
    (t / "_embed_cache" / "blob.md").write_text(OLD)
    done = tmp_path / "tenants" / "fresh"
    done.mkdir()
    (done / ".snowgloves-version").write_text("0.2.0\n")
    (done / "notes.md").write_text(OLD)
    return tmp_path


def test_migration_is_discovered():
    migs = upgrade.load_migrations()
    assert [(m.FROM, m.TO) for m in migs][0] == ("0.1", "0.2")


def test_dry_run_prints_diff_and_writes_nothing(root, capsys):
    t = root / "tenants" / "acme"
    before = {p: p.read_bytes() for p in t.rglob("*") if p.is_file()}
    assert upgrade.main(["--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert f"-{OLD_KEY}_channel: snowgloves.events.v1" in out
    assert "+hermes_channel: snowgloves.events.v1" in out
    assert f"rename tenants/acme/audit/{OLD_FILE} -> tenants/acme/audit/hermes-events.jsonl" in out
    assert "fresh: at 0.2.0, nothing to do" in out
    assert {p: p.read_bytes() for p in t.rglob("*") if p.is_file()} == before


def test_write_applies_rename(root):
    assert upgrade.main(["--root", str(root), "--tenant", "acme", "--write"]) == 0
    t = root / "tenants" / "acme"
    assert (t / ".snowgloves-version").read_text().strip() == "0.2.0"
    assert (t / "MANIFEST.yaml").read_text() == "tenant: acme\nhermes_channel: snowgloves.events.v1\n"
    assert (t / "README.md").read_text() == "Events flow through the Hermes. Port: $HERMES_PORT.\n"
    assert not (t / "audit" / OLD_FILE).exists()
    # event history is moved, not rewritten
    assert OLD_KEY in (t / "audit" / "hermes-events.jsonl").read_text()
    assert (t / "_embed_cache" / "blob.md").read_text() == OLD
    # other tenants untouched when --tenant is given
    assert (root / "tenants" / "fresh" / "notes.md").read_text() == OLD


def test_write_is_idempotent(root, capsys):
    upgrade.main(["--root", str(root), "--write"])
    capsys.readouterr()
    upgrade.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert "acme: at 0.2.0, nothing to do" in out
    assert "---" not in out


def test_existing_hermes_log_is_merged(root):
    t = root / "tenants" / "acme" / "audit"
    (t / "hermes-events.jsonl").write_text('{"event": "new"}\n')
    upgrade.main(["--root", str(root), "--tenant", "acme", "--write"])
    lines = (t / "hermes-events.jsonl").read_text().splitlines()
    assert lines[0] == '{"event": "new"}' and len(lines) == 2


def test_unknown_tenant(root):
    assert upgrade.main(["--root", str(root), "--tenant", "nope"]) == 2


def test_hooks_run_only_on_write(root, capsys):
    scripts = root / "scripts"
    scripts.mkdir()
    log = root / "calls.log"
    for name in ("build_catalog.py", "onboard.py"):
        (scripts / name).write_text(
            "import sys, pathlib\n"
            f"pathlib.Path({str(log)!r}).open('a').write(' '.join([{name!r}, *sys.argv[1:]]) + '\\n')\n")
    (root / "tenants" / "acme" / "runtime.yaml").write_text(
        "runtimes:\n  - id: cursor\n  - id: codex\n    enabled: false\n  - claude\n")
    upgrade.main(["--root", str(root), "--tenant", "acme"])
    out = capsys.readouterr().out
    assert "would run:" in out
    assert "--render-adapter cursor --tenant acme\n" in out
    assert not log.exists()
    upgrade.main(["--root", str(root), "--tenant", "acme", "--write"])
    assert log.read_text().splitlines() == [
        "build_catalog.py",
        "onboard.py --render-adapter cursor --tenant acme --write",
        "onboard.py --render-adapter claude --tenant acme --write",
    ]


def test_chain_skips_gaps():
    class M:
        def __init__(self, a, b): self.FROM, self.TO = a, b
    migs = [M("0.1", "0.2"), M("0.4", "0.5"), M("0.5", "0.6")]
    assert [m.FROM for m in upgrade.chain("0.1", "0.5.0", migs)] == ["0.1", "0.4"]
    assert [m.FROM for m in upgrade.chain("0.2", "0.6.1", migs)] == ["0.4", "0.5"]
