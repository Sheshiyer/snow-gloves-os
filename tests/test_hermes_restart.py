"""The Hermes bus rebinds its port immediately after a restart (EADDRINUSE seen on Coding 01 under launchd)."""
from __future__ import annotations

import http.client
import threading

import hermes  # scripts/ is on sys.path via tests/conftest.py


def start(port):
    server = hermes.BusServer(("127.0.0.1", port), hermes.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def healthz(port):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/healthz")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


def stop(server):
    server.shutdown()
    server.server_close()


def test_the_bus_server_reuses_its_address():
    assert hermes.BusServer.allow_reuse_address is True


def test_a_quick_restart_after_close_binds_the_same_port():
    first = start(0)
    port = first.server_address[1]
    try:
        # Served connections are closed by the server side, leaving TIME_WAIT on this port.
        assert healthz(port) == 200
        assert healthz(port) == 200
    finally:
        stop(first)
    second = start(port)  # raises OSError(EADDRINUSE) without SO_REUSEADDR
    try:
        assert second.server_address[1] == port
        assert healthz(port) == 200
    finally:
        stop(second)
