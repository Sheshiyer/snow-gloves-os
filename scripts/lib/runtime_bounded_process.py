import os, sys, math, time, signal, selectors, subprocess

def run_bounded(argv, env, timeout=15.0, max_output=4096) -> bytes:
    if sys.platform != "linux":
        raise RuntimeError("Bounded process held")
    if type(argv) is not list or not argv or not all(type(x) is str and len(x) > 0 and '\x00' not in x for x in argv):
        raise RuntimeError("Bounded process held")
    if type(env) is not dict or not all(type(k) is str and type(v) is str and k and "=" not in k and '\x00' not in k and '\x00' not in v for k, v in env.items()):
        raise RuntimeError("Bounded process held")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not (0.05 <= timeout <= 30.0):
        raise RuntimeError("Bounded process held")
    if type(max_output) is not int or isinstance(max_output, bool) or not (1 <= max_output <= 16384):
        raise RuntimeError("Bounded process held")

    deadline = time.monotonic() + float(timeout)
    proc = None
    sel = None
    out_chunks, err_len, total_len = [], 0, 0
    stdout_eof, stderr_eof = False, False

    def cleanup_group(pgid):
        if pgid and pgid > 1:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                pass

    try:
        proc = subprocess.Popen(
            argv, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True
        )
        pgid = proc.pid
        sel = selectors.DefaultSelector()
        os.set_blocking(proc.stdout.fileno(), False)
        os.set_blocking(proc.stderr.fileno(), False)
        sel.register(proc.stdout, selectors.EVENT_READ, data='stdout')
        sel.register(proc.stderr, selectors.EVENT_READ, data='stderr')

        while not (stdout_eof and stderr_eof):
            now = time.monotonic()
            rem = deadline - now
            if rem <= 0:
                raise RuntimeError("Bounded process held")
            events = sel.select(timeout=max(0.0, min(rem, 0.1)))
            if not events:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Bounded process held")
                continue
            for key, _ in events:
                stream = key.data
                space = max_output - total_len
                chunk_size = min(1024, max(space + 1, 1))
                fileobj = key.fileobj
                data = fileobj.read(chunk_size)
                if not data:
                    if stream == 'stdout' and not stdout_eof:
                        stdout_eof = True
                        sel.unregister(fileobj)
                    elif stream == 'stderr' and not stderr_eof:
                        stderr_eof = True
                        sel.unregister(fileobj)
                else:
                    if stream == 'stdout':
                        out_chunks.append(data)
                    else:
                        err_len += len(data)
                    total_len += len(data)
                    if total_len > max_output:
                        raise RuntimeError("Bounded process held")

        if time.monotonic() > deadline:
            raise RuntimeError("Bounded process held")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Bounded process held")
        proc.wait(timeout=remaining)
        if time.monotonic() >= deadline:
            raise RuntimeError("Bounded process held")
        if proc.returncode != 0 or err_len > 0:
            raise RuntimeError("Bounded process held")

        try:
            os.killpg(pgid, 0)
            cleanup_group(pgid)
            raise RuntimeError("Bounded process held")
        except ProcessLookupError:
            pass

        res = b"".join(out_chunks)
        if len(res) == 0 or len(res) > max_output:
            raise RuntimeError("Bounded process held")
        return res

    except (KeyboardInterrupt, SystemExit):
        if proc:
            cleanup_group(proc.pid)
            try:
                proc.wait(timeout=0.1)
            except Exception:
                pass
        raise
    except RuntimeError:
        if proc:
            cleanup_group(proc.pid)
            try:
                proc.wait(timeout=0.1)
            except Exception:
                pass
        raise
    except Exception:
        if proc:
            cleanup_group(proc.pid)
            try:
                proc.wait(timeout=0.1)
            except Exception:
                pass
        raise RuntimeError("Bounded process held")
    finally:
        if sel:
            try:
                sel.close()
            except Exception:
                pass
        if proc:
            for p in (proc.stdout, proc.stderr):
                if p:
                    try:
                        p.close()
                    except Exception:
                        pass
