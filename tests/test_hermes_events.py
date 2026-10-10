"""GET /events?since=ISO on the Hermes bus: only newer events, and a clear 400 for a bad timestamp."""
from __future__ import annotations

import http.client
import json
import socketserver
import threading

import pytest

import hermes  # scripts/ is on sys.path via tests/conftest.py

ROWS = [
    {"ts": "2026-10-10T10:00:00+00:00", "kind": "old"},
    {"ts": "2026-10-10T11:00:00.500000+00:00", "kind": "mid"},
    {"ts": "2026-10-10T12:00:00+00:00", "kind": "new"},
    {"kind": "no-ts"},
    {"ts": "not a time", "kind": "bad-ts"},
]


def kinds(events):
    return [e["kind"] for e in events]


def test_events_since_is_strictly_newer_and_skips_unreadable_rows():
    assert kinds(hermes.events_since(ROWS, "2026-10-10T10:30:00Z")) == ["mid", "new"]
    assert kinds(hermes.events_since(ROWS, "2026-10-10T11:00:00.5+00:00")) == ["new"]  # equal is not newer
    assert kinds(hermes.events_since(ROWS, "2026-10-10T12:00:00+00:00")) == []


def test_a_bare_timestamp_is_read_as_utc():
    assert kinds(hermes.events_since(ROWS, "2026-10-10T10:30:00")) == ["mid", "new"]


@pytest.mark.parametrize("bad", ["", "yesterday", "2026-13-45", "10:00"])
def test_a_bad_since_raises(bad):
    with pytest.raises(ValueError):
        hermes.events_since(ROWS, bad)


@pytest.fixture
def bus(tmp_path, monkeypatch):
    log = tmp_path / "events.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in ROWS), encoding="utf-8")
    monkeypatch.setattr(hermes, "LOG", log)
    server = socketserver.TCPServer(("127.0.0.1", 0), hermes.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def test_the_endpoint_without_since_is_unchanged(bus):
    status, body = get(bus, "/events")
    assert status == 200 and body["count"] == 5 and kinds(body["events"]) == ["old", "mid", "new", "no-ts", "bad-ts"]


def test_the_endpoint_filters_with_since(bus):
    status, body = get(bus, "/events?since=2026-10-10T10:30:00Z")
    assert status == 200 and kinds(body["events"]) == ["mid", "new"] and body["count"] == 2


def test_the_endpoint_rejects_a_bad_since_with_400(bus):
    status, body = get(bus, "/events?since=nonsense")
    assert status == 400 and "ISO-8601" in body["error"]
