import os, socket, subprocess, sys, time
from pathlib import Path
import pytest
from ops_workspace import check_workspace, run_workspace, cleanup_children

def _find_free_port_pair() -> tuple[int, int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s1:
        s1.bind(("127.0.0.1", 0))
        p1 = s1.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
        s2.bind(("127.0.0.1", 0))
        p2 = s2.getsockname()[1]
    return p1, p2

def test_tinychild_clean_shutdown():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True)
    cleanup_children([p])
    assert p.poll() is not None

def test_second_spawn_failure_cleans_first(monkeypatch, tmp_path):
    calls = []
    orig_popen = subprocess.Popen
    spawned_procs = []
    def mock_popen(cmd, *a, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            p = orig_popen([sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True)
            spawned_procs.append(p)
            return p
        raise RuntimeError("spawn fail")
    monkeypatch.setattr("ops_workspace.check_workspace", lambda *a, **k: {"ready": True})
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr("shutil.which", lambda b: f"/mock/{b}")
    ui_p, api_p = _find_free_port_pair()
    code = run_workspace(tmp_path / "repo", tmp_path / "data", None, ui_port=ui_p, api_port=api_p)
    assert code == 1
    assert len(spawned_procs) == 1
    assert spawned_procs[0].poll() is not None

def test_occupied_port_and_node24(monkeypatch, tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "scripts").mkdir(); (repo / "scripts" / "infra_cockpit.py").write_text("ok")
    app_dir = repo / "apps" / "infra-block"
    (app_dir / "dist").mkdir(parents=True); (app_dir / "dist" / "index.html").write_text("ok")
    vdir = app_dir / "node_modules" / "vite" / "bin"; vdir.mkdir(parents=True)
    (vdir / "vite.js").write_text("ok")
    data = tmp_path / "data"; (data / "tenants" / "acme").mkdir(parents=True)
    mtime_before = (data / "tenants" / "acme").stat().st_mtime_ns
    monkeypatch.setattr("shutil.which", lambda b: f"/mock/{b}")
    def mock_run(cmd, *a, **kw):
        class R:
            stdout = "v24.0.0"
        return R()
    monkeypatch.setattr(subprocess, "run", mock_run)
    ui_p, api_p = _find_free_port_pair()
    rep = check_workspace(repo, data, "acme", ui_port=ui_p, api_port=api_p)
    assert any(c["id"] == "node_engine" and c["status"] == "ready" for c in rep["checks"])
    assert rep["ready"] is True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", ui_p))
        rep_occ = check_workspace(repo, data, "acme", ui_port=ui_p, api_port=api_p)
        assert rep_occ["ready"] is False
    bad_scope = check_workspace(repo, data, "INVALID_SLUG!", ui_port=ui_p, api_port=api_p)
    assert bad_scope["ready"] is False
    assert (data / "tenants" / "acme").stat().st_mtime_ns == mtime_before

