"""Unit and integration tests for scripts/prepare_mac_bundle.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prepare_mac_bundle import build_bundle, verify_existing_bundle


class TestPrepareMacBundle(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = str(Path(tempfile.mkdtemp(prefix="test_mac_bundle_")).resolve())
        self.repo_dir = Path(self.test_dir) / "repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

        # Construct synthetic allowlisted tree
        self._write_file("README.md", "# Root Readme")
        self._write_file("ISA.md", "# Root ISA")
        self._write_file("VERSION", "1.0.0")
        self._write_file("requirements-ci.txt", "PyYAML==6.0.3")
        self._write_file("scripts/ops_workspace.py", "print('ops workspace')")
        self._write_file("catalog/modules.json", '{"modules": []}')
        self._write_file("catalog/cards/card1.md", "# Card 1")
        self._write_file("agents/primary.yaml", "name: agent")
        self._write_file("adapters/adapter.yml", "type: adapter")
        self._write_file("connectors/db.json", '{"type": "db"}')
        self._write_file("skills/search.md", "# Skill Search")
        self._write_file("prompts/onboard-interview.md", "# Interview for {{runtime_name}}")
        self._write_file("prompts/private.json", '{"private": true}')
        self._write_file("prompts/nested/private.md", "Not a root prompt template")
        self._write_file("workflows/deploy.yaml", "steps: []")
        self._write_file("docs/guide.md", "# Guide")

        # Apps UI structure
        self._write_file("apps/infra-block/index.html", "<html></html>")
        self._write_file("apps/infra-block/package.json", '{"name": "ui"}')
        self._write_file("apps/infra-block/package-lock.json", '{"lockfileVersion": 3}')
        self._write_file("apps/infra-block/tsconfig.json", '{"compilerOptions": {}}')
        self._write_file("apps/infra-block/vite.config.ts", "export default {}")
        self._write_file("apps/infra-block/src/App.tsx", "export const App = () => null;")
        self._write_file("apps/infra-block/src/style.css", "body { margin: 0; }")
        self._write_file("apps/infra-block/public/config.json", '{"api": "/api"}')
        self._write_file("apps/infra-block/dist/index.js", "console.log('built');")
        self._write_file("apps/infra-block/dist/index.js.map", "sourcemap-data")  # Should be excluded

        # Private & excluded items
        self._write_file("private/secret.key", "SUPER_SECRET")
        self._write_file("data/db.sqlite3", "BINARY_DATA")
        self._write_file("tenants/tenant1.json", "{}")
        self._write_file("fleet.yaml", "cluster: secret")
        self._write_file("audit/log.txt", "audit trail")
        self._write_file("_audit/cache.log", "audit cache")
        self._write_file("nodes/node1.json", "{}")
        self._write_file("credentials/tokens.json", "{}")
        self._write_file(".venv/bin/python", "binary")
        self._write_file("node_modules/pkg/index.js", "module.exports = {}")

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_file(self, rel_path: str, content: str) -> Path:
        p = self.repo_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_build_and_verify_success(self) -> None:
        out_dir = Path(self.test_dir) / "bundle_output"
        build_bundle(self.repo_dir, out_dir)

        # Verify bundle succeeds
        self.assertTrue(verify_existing_bundle(out_dir))

        # Check exclusions
        self.assertFalse((out_dir / "private").exists())
        self.assertFalse((out_dir / "data").exists())
        self.assertFalse((out_dir / "fleet.yaml").exists())
        self.assertFalse((out_dir / "_audit").exists())
        self.assertFalse((out_dir / "nodes").exists())
        self.assertFalse((out_dir / "apps/infra-block/dist/index.js.map").exists())

        # Check inclusions
        self.assertTrue((out_dir / "MANIFEST.json").exists())
        self.assertTrue((out_dir / "VERIFY.py").exists())
        self.assertTrue((out_dir / "README-INSTALL.md").exists())
        install_readme = (out_dir / "README-INSTALL.md").read_text(encoding="utf-8")
        self.assertIn("Python 3.11+", install_readme)
        self.assertNotIn("Python 3.10+", install_readme)
        self.assertIn("onboarding interview prompts", install_readme)
        self.assertIn("does not install or start Hermes", install_readme)
        self.assertTrue((out_dir / "apps/infra-block/dist/index.js").exists())
        self.assertTrue((out_dir / "scripts/ops_workspace.py").exists())
        self.assertTrue((out_dir / "prompts/onboard-interview.md").exists())
        self.assertFalse((out_dir / "prompts/private.json").exists())
        self.assertFalse((out_dir / "prompts/nested").exists())

        # Verify MANIFEST includes VERIFY.py and README-INSTALL.md and schema is correct
        manifest_data = json.loads((out_dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest_data.get("schema"), "snowgloves.mac-bundle.v1")
        self.assertIn("VERIFY.py", manifest_data["files"])
        self.assertIn("README-INSTALL.md", manifest_data["files"])

    def test_onboarding_prompt_runs_from_extracted_bundle(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        # Exercise the production CLI from the copied tree, so no source-checkout
        # imports or prompt templates can hide an omitted runtime dependency.
        for relative in (
            "scripts/onboard.py",
            "scripts/lib/__init__.py",
            "scripts/lib/adapters.py",
            "scripts/lib/nodes.py",
            "scripts/lib/paths.py",
            "adapters/codex/adapter.yaml",
            "prompts/onboard-interview.md",
        ):
            target = self.repo_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / relative, target)
        out_dir = Path(self.test_dir) / "bundle_prompt"
        build_bundle(self.repo_dir, out_dir)
        env = {k: v for k, v in os.environ.items() if k not in {
            "PYTHONPATH", "SNOWGLOVES_DATA", "SNOWGLOVES_ROOT", "SNOWGLOVES_NODE",
        }}
        before = set(out_dir.rglob("*"))
        result = subprocess.run(
            [sys.executable, "-B", str(out_dir / "scripts/onboard.py"), "--prompt", "codex"],
            cwd=out_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OpenAI Codex CLI", result.stdout)
        self.assertIn("request_user_input", result.stdout)
        self.assertNotIn("{{runtime_name}}", result.stdout)
        self.assertEqual(set(out_dir.rglob("*")), before)
        self.assertTrue(verify_existing_bundle(out_dir))

    def test_tampered_file_fails_verification(self) -> None:
        out_dir = Path(self.test_dir) / "bundle_output"
        build_bundle(self.repo_dir, out_dir)

        # Tamper a file
        target = out_dir / "scripts/ops_workspace.py"
        target.write_text("print('tampered')", encoding="utf-8")

        self.assertFalse(verify_existing_bundle(out_dir))

    def test_nested_output_refused(self) -> None:
        out_dir = self.repo_dir / "nested_output"
        with self.assertRaises(ValueError):
            build_bundle(self.repo_dir, out_dir)

    def test_symlink_fails_verification(self) -> None:
        out_dir = Path(self.test_dir) / "bundle_output"
        build_bundle(self.repo_dir, out_dir)

        # Create a forbidden symlink inside bundle
        link_path = out_dir / "link_target"
        link_path.symlink_to(out_dir / "README.md")

        self.assertFalse(verify_existing_bundle(out_dir))

    def test_symlink_dir_fails_verification(self) -> None:
        out_dir = Path(self.test_dir) / "bundle_output"
        build_bundle(self.repo_dir, out_dir)

        # Create a symlink directory inside bundle
        link_dir = out_dir / "link_dir"
        link_dir.symlink_to(out_dir / "scripts", target_is_directory=True)

        self.assertFalse(verify_existing_bundle(out_dir))

    def test_extra_untracked_file_fails_verification(self) -> None:
        out_dir = Path(self.test_dir) / "bundle_output"
        build_bundle(self.repo_dir, out_dir)

        # Add untracked extra file
        (out_dir / "unexpected.txt").write_text("malicious", encoding="utf-8")

        self.assertFalse(verify_existing_bundle(out_dir))

    def test_allowed_extras_in_bundle(self) -> None:
        out_dir = Path(self.test_dir) / "bundle_output"
        build_bundle(self.repo_dir, out_dir)

        # Add allowed extra dirs (.venv, node_modules)
        venv_file = out_dir / ".venv/bin/activate"
        venv_file.parent.mkdir(parents=True, exist_ok=True)
        venv_file.write_text("# venv", encoding="utf-8")

        node_file = out_dir / "node_modules/dep/index.js"
        node_file.parent.mkdir(parents=True, exist_ok=True)
        node_file.write_text("# node", encoding="utf-8")

        self.assertTrue(verify_existing_bundle(out_dir))

        # Forbidden extra dir like .git should fail
        git_file = out_dir / ".git/config"
        git_file.parent.mkdir(parents=True, exist_ok=True)
        git_file.write_text("# git", encoding="utf-8")
        self.assertFalse(verify_existing_bundle(out_dir))

    def test_dangling_or_symlink_output_rejected_before_resolve(self) -> None:
        # Dangling symlink as output
        dangling_out = Path(self.test_dir) / "dangling_link"
        dangling_out.symlink_to(Path(self.test_dir) / "nonexistent_target")
        with self.assertRaises(ValueError):
            build_bundle(self.repo_dir, dangling_out)

    def test_local_private_scope_json_rejected(self) -> None:
        self._write_file("catalog/bad.json", '{"scope": {"mode": "local-private"}}')
        self._write_file("catalog/modules.json", '{"scope": {"mode": "local-private"}}')
        out_dir = Path(self.test_dir) / "bundle_output_bad_json"
        with self.assertRaises(ValueError):
            build_bundle(self.repo_dir, out_dir)


if __name__ == "__main__":
    unittest.main()
