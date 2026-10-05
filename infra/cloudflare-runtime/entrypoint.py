import os
import sys

def _verify_containment() -> None:
    if sys.platform != "linux":
        sys.stderr.write("Managed runtime unavailable\n")
        sys.stderr.flush()
        sys.exit(1)

    if os.getppid() != 1:
        sys.stderr.write("Managed runtime unavailable\n")
        sys.stderr.flush()
        sys.exit(1)

    try:
        with open("/proc/1/comm", "rb") as f:
            comm = f.read().strip()
        if comm != b"tini":
            sys.stderr.write("Managed runtime unavailable\n")
            sys.stderr.flush()
            sys.exit(1)
    except Exception:
        sys.stderr.write("Managed runtime unavailable\n")
        sys.stderr.flush()
        sys.exit(1)

    try:
        stat_proc_1 = os.stat("/proc/1")
        if stat_proc_1.st_uid != os.geteuid():
            sys.stderr.write("Managed runtime unavailable\n")
            sys.stderr.flush()
            sys.exit(1)
    except Exception:
        sys.stderr.write("Managed runtime unavailable\n")
        sys.stderr.flush()
        sys.exit(1)

_verify_containment()

for path in ("/opt/snowgloves/runtime", "/opt/snowgloves/runtime/scripts"):
    if path not in sys.path:
        sys.path.insert(0, path)

from lib.runtime_managed_service import main

if __name__ == "__main__":
    sys.exit(main())
