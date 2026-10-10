import argparse, importlib.util, json, os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path

DEFAULT_UI_PORT = 18760
DEFAULT_API_PORT = 18761
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def _port_free(p: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", p))
            return True
    except Exception:
        return False

def _port_connectable(p: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            s.connect(("127.0.0.1", p))
            return True
    except Exception:
        return False

def _no_symlink(p: Path) -> bool:
    cur = p
    while True:
        if cur.is_symlink(): return False
        if cur.parent == cur: break
        cur = cur.parent
    return True

def _validate_port(port: int) -> bool:
    return isinstance(port, int) and 1024 <= port <= 65535

def check_workspace(repo: Path, data: Path, tenant: str | None = None, ui_port: int = DEFAULT_UI_PORT, api_port: int = DEFAULT_API_PORT) -> dict:
    checks = []
    def add(cid: str, ok: bool): checks.append({"id": cid, "status": "ready" if ok else "held"})
    add("python_version", sys.version_info >= (3, 10))
    add("yaml_module", importlib.util.find_spec("yaml") is not None)
    n_bin, npm_bin = shutil.which("node"), shutil.which("npm")
    add("cli_tools", bool(n_bin and npm_bin))
    node_ver_ok = False
    if n_bin:
        try:
            r = subprocess.run([n_bin, "--version"], capture_output=True, text=True, timeout=2)
            m = re.search(r"v(\d+)\.(\d+)", r.stdout)
            if m:
                maj, min_ = int(m.group(1)), int(m.group(2))
                node_ver_ok = (maj == 20 and min_ >= 19) or (maj == 22 and min_ >= 12) or (maj > 22)
        except Exception:
            pass
    add("node_engine", node_ver_ok)
    api_script = repo / "scripts" / "infra_cockpit.py"
    dist = repo / "apps" / "infra-block" / "dist" / "index.html"
    vite = repo / "apps" / "infra-block" / "node_modules" / "vite" / "bin" / "vite.js"
    add("build_artifacts", api_script.is_file() and dist.is_file() and vite.is_file())

    ports_valid = _validate_port(ui_port) and _validate_port(api_port) and ui_port != api_port
    ports_ok = ports_valid and _port_free(ui_port) and _port_free(api_port)
    add("ports_available", ports_ok)

    data_p = data.resolve()
    repo_p = repo.resolve()
    data_distinct = _no_symlink(data) and _no_symlink(repo) and data_p != repo_p
    try:
        data_p.relative_to(repo_p)
        not_nested = False
    except ValueError:
        try:
            repo_p.relative_to(data_p)
            not_nested = False
        except ValueError:
            not_nested = True

    data_ok = data_distinct and not_nested
    tdir = data / "tenants"
    data_ok = data_ok and tdir.is_dir() and _no_symlink(tdir)
    if tenant is not None:
        t_ok = bool(len(tenant) <= 64 and SLUG_RE.match(tenant))
        tp = tdir / tenant
        data_ok = data_ok and t_ok and tp.is_dir() and _no_symlink(tp)
    add("data_isolation", data_ok)

    all_ready = all(c["status"] == "ready" for c in checks)
    return {"ready": all_ready, "checks": checks, "scope": {"tenant": tenant, "mode": "local-private"}, "physicalAcceptance": "unverified"}

def cleanup_children(children: list[subprocess.Popen]):
    for c in children:
        if c.poll() is None:
            try: os.killpg(c.pid, signal.SIGTERM)
            except Exception: pass
    t_end = time.time() + 2.0
    for c in children:
        if c.poll() is None:
            rem = max(0.01, t_end - time.time())
            try: c.wait(timeout=rem)
            except Exception:
                if c.poll() is None:
                    try: os.killpg(c.pid, signal.SIGKILL)
                    except Exception: pass
                    try: c.wait(timeout=0.5)
                    except Exception: pass

def _wait_ready(procs: list[subprocess.Popen], ports: list[int], timeout: float = 10.0) -> bool:
    t_end = time.time() + timeout
    while time.time() < t_end:
        if any(c.poll() is not None for c in procs): return False
        if all(_port_connectable(p) for p in ports):
            if all(c.poll() is None for c in procs):
                return True
        time.sleep(0.1)
    return False

def run_workspace(repo: Path, data: Path, tenant: str | None = None, ui_port: int = DEFAULT_UI_PORT, api_port: int = DEFAULT_API_PORT) -> int:
    if not (_validate_port(ui_port) and _validate_port(api_port) and ui_port != api_port):
        return 1
    repo_root = repo.resolve()
    data_root = data.resolve()
    if not check_workspace(repo, data, tenant, ui_port=ui_port, api_port=api_port).get("ready"):
        return 1
    node_bin = shutil.which("node")
    if not node_bin: return 1
    app_dir = repo_root / "apps" / "infra-block"
    vite_bin = app_dir / "node_modules" / "vite" / "bin" / "vite.js"
    cmd_api = [sys.executable, "-B", str(repo_root / "scripts" / "infra_cockpit.py"), "--repo-root", str(repo_root), "--port", str(api_port), "--ui-port", str(ui_port), "--data-root", str(data_root), "--no-probe"]
    if tenant: cmd_api.extend(["--tenant", tenant])
    cmd_app = [node_bin, str(vite_bin), "preview", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"]
    app_env = os.environ.copy()
    app_env["SNOWGLOVES_COCKPIT_PORT"] = str(api_port)
    children: list[subprocess.Popen] = []
    try:
        children.append(subprocess.Popen(cmd_api, cwd=str(repo_root), start_new_session=True))
        children.append(subprocess.Popen(cmd_app, cwd=str(app_dir), env=app_env, start_new_session=True))
        if not _wait_ready(children, [ui_port, api_port], timeout=10.0):
            return 1
        sys.stdout.write(f"http://127.0.0.1:{ui_port}/\n"); sys.stdout.flush()
        while True:
            if any(c.poll() is not None for c in children): return 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    except Exception:
        return 1
    finally:
        cleanup_children(children)

def _port_arg(v: str) -> int:
    try:
        val = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{v} is not a valid integer")
    if not (1024 <= val <= 65535):
        raise argparse.ArgumentTypeError(f"port {val} out of range (1024..65535)")
    return val

def main() -> int:
    p = argparse.ArgumentParser(prog="ops_workspace")
    sub = p.add_subparsers(dest="subcommand", required=True)
    for name in ("check", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--data-root", required=True, type=Path)
        sp.add_argument("--tenant", default=None, type=str)
        sp.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
        sp.add_argument("--ui-port", default=DEFAULT_UI_PORT, type=_port_arg)
        sp.add_argument("--api-port", default=DEFAULT_API_PORT, type=_port_arg)
    def stop_owned(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_owned)
    try:
        args = p.parse_args()
        if args.ui_port == args.api_port:
            return 2
        if args.subcommand == "check":
            res = check_workspace(args.repo_root, args.data_root, args.tenant, ui_port=args.ui_port, api_port=args.api_port)
            sys.stdout.write(json.dumps(res) + "\n")
            return 0 if res["ready"] else 1
        elif args.subcommand == "run":
            return run_workspace(args.repo_root, args.data_root, args.tenant, ui_port=args.ui_port, api_port=args.api_port)
    except Exception:
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
