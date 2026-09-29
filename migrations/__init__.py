"""Tenant schema migrations.

Each module is named `v<A>_<B>_to_v<C>_<D>.py` and exposes:

  FROM = "A.B"
  TO = "C.D"
  def migrate(tenant_dir: pathlib.Path) -> list[str]   # mutate in place, return notes

`scripts/upgrade.py` runs them against a scratch copy of the tenant, diffs the
copy against the original, and only writes back with `--write`.
"""
