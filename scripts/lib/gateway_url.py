"""Gateway URL parsing shared by scripts/fleet/doctor.py and scripts/fleet/gateway_client.py.

A gateway URL is `[scheme://]host[:port][/path]`. No scheme means http; the default port is 443
for https and 80 for http. Callers that want the OmniRoute default (20128) for a bare http host
check `has_explicit_port` first.
"""
from __future__ import annotations

import re

_URL = re.compile(r"^\s*(?:(https?)://)?([^:/\s]+)(?::(\d+))?", re.I)


def parse_gateway_url(url: str | None) -> tuple[str | None, str | None, int | None]:
    """(scheme, host, port), or (None, None, None) when the URL does not parse."""
    m = _URL.match(url or "")
    if not m:
        return None, None, None
    scheme = (m.group(1) or "http").lower()
    return scheme, m.group(2), int(m.group(3) or (443 if scheme == "https" else 80))


def has_explicit_port(url: str | None) -> bool:
    """True when the URL names a port, with or without a scheme (`coding-mac:8080` counts)."""
    m = _URL.match(url or "")
    return bool(m and m.group(3))
