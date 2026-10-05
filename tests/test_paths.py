"""scripts/lib/paths.py: code root vs data root ($SNOWGLOVES_DATA) resolution."""
from pathlib import Path

import pytest

from lib import paths

CODE = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv(paths.ENV, raising=False)


def test_code_root_is_this_checkout():
    assert paths.code_root() == CODE
    assert (paths.code_root() / "scripts" / "lib" / "paths.py").is_file()


def test_unset_env_resolves_to_code_root(no_env):
    assert paths.data_root() == CODE
    assert paths.tenants_dir() == CODE / "tenants"
    assert paths.fleet_file() == CODE / "fleet.yaml"
    assert paths.nodes_dir() == CODE / "nodes"
    assert paths.audit_dir() == CODE / "_audit"


def test_blank_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv(paths.ENV, "   ")
    assert paths.data_root() == CODE


def test_env_sets_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV, str(tmp_path))
    assert paths.data_root() == tmp_path.resolve()
    assert paths.tenants_dir() == tmp_path.resolve() / "tenants"
    assert paths.fleet_file() == tmp_path.resolve() / "fleet.yaml"
    assert paths.audit_dir() == tmp_path.resolve() / "_audit"


def test_env_expands_user(monkeypatch):
    monkeypatch.setenv(paths.ENV, "~/sg-data-not-real")
    assert paths.data_root() == (Path.home() / "sg-data-not-real").resolve()


def test_override_beats_env(tmp_path, monkeypatch):
    env_dir, flag_dir = tmp_path / "env", tmp_path / "flag"
    env_dir.mkdir()
    flag_dir.mkdir()
    monkeypatch.setenv(paths.ENV, str(env_dir))
    assert paths.data_root(flag_dir) == flag_dir.resolve()
    assert paths.data_root(str(flag_dir)) == flag_dir.resolve()
    assert paths.tenants_dir(flag_dir) == flag_dir.resolve() / "tenants"
    assert paths.fleet_file(flag_dir) == flag_dir.resolve() / "fleet.yaml"


def test_override_without_env(tmp_path, no_env):
    assert paths.data_root(tmp_path) == tmp_path.resolve()


def test_nodes_dir_falls_back_to_code_templates(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV, str(tmp_path))
    assert paths.nodes_dir() == CODE / "nodes"  # data checkout has no nodes/ yet
    (tmp_path / "nodes").mkdir()
    assert paths.nodes_dir() == tmp_path.resolve() / "nodes"


def test_fleet_file_does_not_fall_back(tmp_path, monkeypatch):
    """The instance inventory is private: an empty data checkout means no fleet.yaml, not the code root's."""
    monkeypatch.setenv(paths.ENV, str(tmp_path))
    assert not paths.fleet_file().exists()


def test_onboard_resolve_roots_precedence(tmp_path, monkeypatch):
    import onboard

    code, data, env = tmp_path / "code", tmp_path / "data", tmp_path / "env"
    for d in (code, data, env):
        d.mkdir()
    monkeypatch.delenv("SNOWGLOVES_ROOT", raising=False)
    monkeypatch.delenv(paths.ENV, raising=False)
    assert onboard.resolve_roots(None, None) == (onboard.CODE_ROOT, onboard.CODE_ROOT, onboard.CODE_ROOT)
    monkeypatch.setenv(paths.ENV, str(env))
    assert onboard.resolve_roots(None, None)[1] == env.resolve()
    # an explicit --root still moves code and data together (tests and SNOWGLOVES_ROOT callers rely on it)
    assert onboard.resolve_roots(code, None)[:2] == (code, code)
    # --data wins over both
    assert onboard.resolve_roots(code, data)[:2] == (code, data.resolve())
    # wing profiles: <data>/nodes when present, else the code root's templates
    assert onboard.resolve_roots(code, data)[2] == code
    (data / "nodes").mkdir()
    assert onboard.resolve_roots(code, data)[2] == data.resolve()


def test_onboard_data_flag_writes_tenants_outside_the_code_root(tmp_path, monkeypatch):
    import onboard

    monkeypatch.delenv(paths.ENV, raising=False)
    code, data = tmp_path / "code", tmp_path / "data"
    code.mkdir()
    data.mkdir()
    answers = iter(["Bakery Co", "bakery", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert onboard.main(["--root", str(code), "--data", str(data), "--init-tenant"]) == 0
    assert (data / "tenants" / "bakery" / "sources.yaml").is_file()
    assert not (code / "tenants").exists()
