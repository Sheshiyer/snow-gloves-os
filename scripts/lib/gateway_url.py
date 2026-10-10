"""Gateway URL parsing shared by scripts/fleet/doctor.py and scripts/fleet/gateway_client.py.

A gateway URL is `[scheme://]host[:port][/path]`. No scheme means http; the default port is 443
for https and 80 for http. Callers that want the OmniRoute default (20128) for a bare http host
check `has_explicit_port` first.
"""
from __future__ import annotations

import re

# The whole string must match: the authority is a bare host name and an optional port, and anything
# after it starts a path, query or fragment. Userinfo (`user@host`, `gw.example:443@other.example`),
# other schemes and trailing junk do not parse, so a URL can never be read as a host it does not reach.
_URL = re.compile(r"\s*(?:(https?)://)?([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?::(\d{1,5}))?"
                  r"(?:[/?#]\S*)?\s*", re.I)


def _match(url: str | None) -> re.Match | None:
    m = _URL.fullmatch(url or "")
    if m and m.group(3) and not 0 < int(m.group(3)) <= 65535:
        return None
    return m


def parse_gateway_url(url: str | None) -> tuple[str | None, str | None, int | None]:
    """(scheme, host, port), or (None, None, None) when the URL does not parse."""
    m = _match(url)
    if not m:
        return None, None, None
    scheme = (m.group(1) or "http").lower()
    return scheme, m.group(2), int(m.group(3) or (443 if scheme == "https" else 80))


def has_explicit_port(url: str | None) -> bool:
    """True when the URL names a port, with or without a scheme (`coding-mac:8080` counts)."""
    m = _match(url)
    return bool(m and m.group(3))
