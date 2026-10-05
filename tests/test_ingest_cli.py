"""Exercise ingestion through the private-data seam, not only its glob helper."""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_relative_sources_resolve_against_private_data_root(tmp_path):
    tenant = tmp_path / "tenants" / "sample"
    wiki = tenant / "wiki"
    wiki.mkdir(parents=True)
    note = wiki / "context.md"
    note.write_text("Private tenant fixture.\n")
    (tenant / "sources.yaml").write_text(yaml.safe_dump({
        "tenant": "sample",
        "sources": [{"path": "tenants/sample/wiki", "include_glob": ["**/*.md"]}],
    }))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ingest.py"), "sample"],
        env=dict(os.environ, SNOWGLOVES_DATA=str(tmp_path)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((tenant / "ingest-plan.json").read_text())
    assert plan["tenant"] == "sample"
    assert plan["files"] == [{"path": str(note), "size": note.stat().st_size}]
    assert plan["skipped"] == []
