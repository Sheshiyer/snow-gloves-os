import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import scope_guard  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_approval_queue(tmp_path, monkeypatch):
    """scope_guard queues tickets under ROOT/tenants/<t>/approvals; keep tracked tenants untouched."""
    monkeypatch.setattr(scope_guard, "ROOT", tmp_path)
