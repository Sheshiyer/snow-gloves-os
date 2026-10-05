"""Linux-only Runtime Managed Service integration module."""

from __future__ import annotations

import base64
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Tuple

from lib.runtime_initializer import InitializingSupervisor
from lib.runtime_managed_http import KEY_RE, create_managed_server
from lib.runtime_management_coordinator import RuntimeManagementCoordinator
from lib.runtime_operation_identity import checkpoint_digest

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_INSTANCE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


@dataclass(frozen=True)
class Config:
    instance_id: str
    image_digest: str
    backup_key_id: str
    backup_key: str
    management_key: str
    backend_key: str
    storage_encryption_key: str
    data_dir: str
    node_executable: str
    runtime_script: str
    backup_cli: str
    initialize_fresh: bool

    def __repr__(self) -> str:
        return (
            f"Config(instance_id={self.instance_id!r}, "
            f"image_digest={self.image_digest!r}, "
            f"backup_key_id={self.backup_key_id!r}, "
            f"data_dir={self.data_dir!r}, "
            f"initialize_fresh={self.initialize_fresh!r}, "
            "secrets=[REDACTED])"
        )


def _validate_keys(
    backup_key_b64: str,
    mgmt_key: str,
    backend_key: str,
    storage_key: str,
) -> bytes:
    if not KEY_RE.fullmatch(mgmt_key):
        raise ValueError("Invalid management key format")
    if not KEY_RE.fullmatch(backend_key):
        raise ValueError("Invalid backend key format")
    if not KEY_RE.fullmatch(storage_key):
        raise ValueError("Invalid storage key format")

    try:
        backup_raw = base64.b64decode(backup_key_b64.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("Invalid canonical base64 backup key") from exc

    if len(backup_raw) != 32:
        raise ValueError("Backup key must decode to exactly 32 bytes")
    if base64.b64encode(backup_raw).decode("ascii") != backup_key_b64:
        raise ValueError("Backup key is not canonical base64")

    text_keys = {mgmt_key, backend_key, storage_key}
    if len(text_keys) != 3:
        raise ValueError("Management, backend, and storage keys must be distinct")

    mgmt_raw = mgmt_key.encode("utf-8")
    backend_raw = backend_key.encode("utf-8")
    storage_raw = storage_key.encode("utf-8")

    all_raw = {backup_raw, mgmt_raw, backend_raw, storage_raw}
    if len(all_raw) != 4:
        raise ValueError("All 4 keys (including decoded backup key) must be distinct")

    return backup_raw


def _build_context(config: Config) -> Dict[str, Any]:
    return {
        "instanceId": config.instance_id,
        "imageDigest": config.image_digest,
        "keyId": config.backup_key_id,
        "runtimeVersion": "3.8.50",
    }


def _validate_pure_config(config: Config) -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Linux only")
    if type(config) is not Config or type(config.initialize_fresh) is not bool:
        raise ValueError("Invalid config type")
    if not _INSTANCE_ID_RE.fullmatch(config.instance_id):
        raise ValueError("Invalid instance id")
    if not _HEX64_RE.fullmatch(config.image_digest):
        raise ValueError("Invalid image digest")
    if not _KEY_ID_RE.fullmatch(config.backup_key_id):
        raise ValueError("Invalid backup key id")

    _validate_keys(
        config.backup_key,
        config.management_key,
        config.backend_key,
        config.storage_encryption_key,
    )

    ctx = _build_context(config)
    checkpoint_digest(ctx, "a" * 32)


def _verify_no_symlink_ancestors(path: str) -> None:
    parts = os.path.abspath(path).split(os.sep)
    current = "/"
    for part in parts:
        if not part:
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ValueError(f"Symlink detected in path hierarchy: {current}")


PathSnapshot = Tuple[int, int, int, int, int, int, int]


def _stat_and_verify_trusted_path(path: str) -> PathSnapshot:
    if not os.path.isabs(path):
        raise ValueError(f"Path must be absolute: {path}")
    real = os.path.realpath(path)
    if real != path:
        raise ValueError(f"Path is not canonical: {path}")
    _verify_no_symlink_ancestors(path)

    st = os.stat(path, follow_symlinks=False)
    if not os.path.isfile(path) or os.path.islink(path):
        raise ValueError(f"Trusted path must be a regular non-symlink file: {path}")

    euid = os.geteuid()
    if st.st_uid != 0 and st.st_uid != euid:
        raise ValueError(f"Trusted path must be owned by root or current euid: {path}")

    mode = st.st_mode
    if (mode & 0o022) != 0:
        raise ValueError(f"Trusted path must not be group/other writable: {path}")

    return (
        st.st_dev,
        st.st_ino,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
        mode,
        st.st_uid,
    )


def _verify_data_dir(data_dir: str, initialize_fresh: bool) -> None:
    if not os.path.isabs(data_dir):
        raise ValueError(f"DATA_DIR must be absolute: {data_dir}")
    real = os.path.realpath(data_dir)
    if real != data_dir:
        raise ValueError(f"DATA_DIR must be canonical: {data_dir}")
    _verify_no_symlink_ancestors(data_dir)

    st = os.stat(data_dir, follow_symlinks=False)
    if not os.path.isdir(data_dir) or os.path.islink(data_dir):
        raise ValueError(f"DATA_DIR must be a regular directory: {data_dir}")

    euid = os.geteuid()
    if st.st_uid != euid:
        raise ValueError(f"DATA_DIR must be owned by current euid: {data_dir}")
    if (st.st_mode & 0o7777) != 0o700:
        raise ValueError(f"DATA_DIR mode must be exactly 0700: {data_dir}")

    entries = os.listdir(data_dir)
    if initialize_fresh:
        if len(entries) != 0:
            raise ValueError(f"Fresh DATA_DIR must be empty: {data_dir}")
    else:
        sqlite_path = os.path.join(data_dir, "storage.sqlite")
        if not os.path.exists(sqlite_path):
            raise ValueError("Existing mode requires storage.sqlite present in DATA_DIR")
    return (st.st_dev, st.st_ino, st.st_uid, st.st_mode)


def load_config(env: Mapping[str, str]) -> Config:
    required_keys = [
        "SG_INSTANCE_ID",
        "SG_IMAGE_DIGEST",
        "SG_BACKUP_KEY_ID",
        "SG_BACKUP_KEY",
        "SG_MANAGEMENT_KEY",
        "SG_BACKEND_KEY",
        "STORAGE_ENCRYPTION_KEY",
        "DATA_DIR",
        "SG_NODE_EXECUTABLE",
        "SG_RUNTIME_SCRIPT",
        "SG_BACKUP_CLI",
    ]
    for k in required_keys:
        if k not in env or not env[k]:
            raise ValueError(f"Missing required environment variable: {k}")

    fresh_val = env.get("SG_INITIALIZE_FRESH")
    if fresh_val is not None and fresh_val != "1":
        raise ValueError("SG_INITIALIZE_FRESH accepts only absent or '1'")
    initialize_fresh = fresh_val == "1"

    cfg = Config(
        instance_id=env["SG_INSTANCE_ID"],
        image_digest=env["SG_IMAGE_DIGEST"],
        backup_key_id=env["SG_BACKUP_KEY_ID"],
        backup_key=env["SG_BACKUP_KEY"],
        management_key=env["SG_MANAGEMENT_KEY"],
        backend_key=env["SG_BACKEND_KEY"],
        storage_encryption_key=env["STORAGE_ENCRYPTION_KEY"],
        data_dir=env["DATA_DIR"],
        node_executable=env["SG_NODE_EXECUTABLE"],
        runtime_script=env["SG_RUNTIME_SCRIPT"],
        backup_cli=env["SG_BACKUP_CLI"],
        initialize_fresh=initialize_fresh,
    )
    _validate_pure_config(cfg)
    return cfg


def _snapshot_all_paths(config: Config) -> Dict[str, PathSnapshot]:
    snapshots = {
        "node": _stat_and_verify_trusted_path(config.node_executable),
        "runtime": _stat_and_verify_trusted_path(config.runtime_script),
        "backup": _stat_and_verify_trusted_path(config.backup_cli),
    }
    if not snapshots["node"][5] & 0o111 or not os.access(config.node_executable, os.X_OK):
        raise ValueError("Node executable permission required")
    if snapshots["backup"][5] & 0o111:
        raise ValueError("Backup CLI must not be executable")
    return snapshots


def _verify_snapshots(before: Dict[str, PathSnapshot], config: Config) -> None:
    after = _snapshot_all_paths(config)
    if before != after:
        raise RuntimeError("Trusted path attributes modified during lifecycle")


def run_service(config: Config) -> None:
    _validate_pure_config(config)
    root_identity = _verify_data_dir(config.data_dir, config.initialize_fresh)
    snap_before = _snapshot_all_paths(config)

    command = [config.node_executable, config.runtime_script]
    supervisor = InitializingSupervisor(
        data_dir=config.data_dir,
        command=command,
        storage_key=config.storage_encryption_key,
        management_secret=config.management_key,
        admission=False,
        runtime_port=8081,
    )

    server = None
    server_thread = None
    serve_entered = threading.Event()
    stop_event = threading.Event()
    mgmt_lock = threading.Lock()

    def sig_handler(_signum: int, _frame: Any) -> None:
        stop_event.set()

    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)

    try:
        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)

        _verify_snapshots(snap_before, config)
        if _verify_data_dir(config.data_dir, config.initialize_fresh) != root_identity:
            raise RuntimeError("Data root identity changed")
        if stop_event.is_set():
            return
        if config.initialize_fresh:
            supervisor.initialize_fresh(authorized=True, timeout=60, cancel_event=stop_event)
        else:
            supervisor.start()

        if stop_event.is_set():
            return
        _verify_snapshots(snap_before, config)
        if _verify_data_dir(config.data_dir, False) != root_identity:
            raise RuntimeError("Data root identity changed")

        # Verify child health before exposing any management request.
        grace_deadline = time.monotonic() + 10.0
        init_healthy = False
        while time.monotonic() < grace_deadline:
            if stop_event.is_set():
                return
            if supervisor.child_pid is None:
                raise RuntimeError("Child died during startup grace")
            if supervisor._check_http_health() is True:
                if time.monotonic() >= grace_deadline:
                    raise RuntimeError("Late startup health")
                init_healthy = True
                break
            stop_event.wait(0.1)
        if stop_event.is_set():
            return
        if not init_healthy:
            raise RuntimeError("Child failed startup health")
        _verify_snapshots(snap_before, config)
        if _verify_data_dir(config.data_dir, False) != root_identity:
            raise RuntimeError("Data root identity changed")

        coordinator = RuntimeManagementCoordinator(
            supervisor=supervisor,
            context=_build_context(config),
            backup_key_base64=config.backup_key,
            node_executable=config.node_executable,
            backup_cli_path=config.backup_cli,
        )

        def guarded_checkpoint(payload: Any) -> Any:
            with mgmt_lock:
                return coordinator.checkpoint(payload)

        def guarded_restore(payload: Any) -> Any:
            with mgmt_lock:
                return coordinator.restore(payload)

        def health_probe() -> bool:
            return supervisor._check_http_health()

        server = create_managed_server(
            checkpoint=guarded_checkpoint,
            restore=guarded_restore,
            health_probe=health_probe,
            management_key=config.management_key,
            backend_key=config.backend_key,
            storage_key=config.storage_encryption_key,
            operation_context=_build_context(config),
            upstream_port=8081,
            host="0.0.0.0",
            port=8080,
            admission_probe=lambda: False,
        )

        def _serve_worker() -> None:
            serve_entered.set()
            server.serve_forever()

        server_thread = threading.Thread(target=_serve_worker, daemon=True)
        server_thread.start()

        if not serve_entered.wait(timeout=10.0):
            raise RuntimeError("Server thread failed to start serve loop")

        # Main supervision loop
        while not stop_event.is_set():
            if not server_thread.is_alive():
                raise RuntimeError("Server thread terminated unexpectedly")
            if mgmt_lock.acquire(blocking=False):
                try:
                    if supervisor.child_pid is None:
                        raise RuntimeError("Child process terminated unexpectedly")
                    if not supervisor._check_http_health():
                        raise RuntimeError("Child health check failed")
                finally:
                    mgmt_lock.release()

            stop_event.wait(timeout=0.5)

    finally:
        cleanup_error = None

        if server is not None and serve_entered.is_set():
            try:
                server.shutdown()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc

        if server is not None:
            try:
                server.server_close()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc

        if server_thread is not None and server_thread.is_alive():
            server_thread.join(timeout=5.0)

        acquired = mgmt_lock.acquire(timeout=60.0)
        if acquired:
            try:
                supervisor.stop()
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            finally:
                mgmt_lock.release()
        elif cleanup_error is None:
            cleanup_error = RuntimeError("Management cleanup held")

        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)

        if cleanup_error is not None:
            raise RuntimeError("Cleanup failed") from cleanup_error


def main() -> int:
    try:
        cfg = load_config(os.environ)
        run_service(cfg)
        return 0
    except KeyboardInterrupt:
        return 0
    except SystemExit:
        raise
    except BaseException:
        sys.stderr.write("Managed runtime unavailable\n")
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
