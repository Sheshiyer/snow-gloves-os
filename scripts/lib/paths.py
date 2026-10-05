"""Where Snow Gloves finds its code and its instance data.

The platform (scripts, catalog, agents, adapters, the `_demo` fixture) lives in
this checkout: `code_root()`. Instance data (brand tenants, the fleet inventory,
wing profiles, the audit log) can live in a separate private checkout:

    data_root(override)  ->  override, else $SNOWGLOVES_DATA, else code_root()

With SNOWGLOVES_DATA unset every path resolves exactly as before the split.

    paths.tenants_dir()   data_root()/tenants
    paths.fleet_file()    data_root()/fleet.yaml
    paths.nodes_dir()     data_root()/nodes when it exists, else code_root()/nodes
    paths.audit_dir()     data_root()/_audit
"""

from __future__ import annotations

import os
from pathlib import Path

ENV = "SNOWGLOVES_DATA"

_CODE_ROOT = Path(__file__).resolve().parents[2]


def code_root() -> Path:
    """This checkout (the folder that holds scripts/, catalog/, agents/)."""
    return _CODE_ROOT


def data_root(override: str | os.PathLike | None = None) -> Path:
    """Instance data checkout: the override, else $SNOWGLOVES_DATA, else code_root()."""
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get(ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return code_root()


def tenants_dir(override: str | os.PathLike | None = None) -> Path:
    return data_root(override) / "tenants"


def fleet_file(override: str | os.PathLike | None = None) -> Path:
    return data_root(override) / "fleet.yaml"


def nodes_dir(override: str | os.PathLike | None = None) -> Path:
    """Wing profiles: the data checkout's nodes/ when it has one, else the templates shipped here."""
    data = data_root(override) / "nodes"
    return data if data.is_dir() else code_root() / "nodes"


def audit_dir(override: str | os.PathLike | None = None) -> Path:
    return data_root(override) / "_audit"
