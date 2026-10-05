"""infra/ cloud gateway: render cloud-init with OpenTofu and check what lands on the instance.

Skipped when `tofu` is not installed. Provider-level `tofu validate` runs in CI (it needs the
provider downloads); this test is offline.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra" / "aws-gateway" / "cloud-init.yaml.tftpl"
VARS = {
    "name": "sg-gw", "region": "eu-west-3", "omniroute_version": "3.8.50", "tailnet_hostname": "sg-gw",
    "backup_bucket": "sg-gw-backups-111122223333", "ssm_prefix": "/sg-gw",
    "cf_ranges": "173.245.48.0/20 2400:cb00::/32",
}

pytestmark = pytest.mark.skipif(not shutil.which("tofu"), reason="OpenTofu not installed")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> dict:
    work = tmp_path_factory.mktemp("tofu-console")
    args = ", ".join(f'{k}="{v}"' for k, v in VARS.items())
    expr = f'templatefile("{TEMPLATE}", {{{args}}})\n'
    proc = subprocess.run(["tofu", "console", "-no-color"], input=expr, capture_output=True, text=True,
                          cwd=work, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    assert out.startswith("<<EOT"), out[:200]
    body = out.split("\n", 1)[1].rsplit("EOT", 1)[0]
    assert body.startswith("#cloud-config")
    return {"text": body, "doc": yaml.safe_load(body)}


def files(doc: dict) -> dict[str, str]:
    return {f["path"]: f["content"] for f in doc["write_files"]}


def test_every_template_variable_is_filled(rendered):
    assert "${" not in rendered["text"] and "%{" not in rendered["text"]
    for value in VARS.values():
        assert value in rendered["text"]


def test_omniroute_binds_loopback_only_and_caddy_trusts_cloudflare(rendered):
    f = files(rendered["doc"])
    unit = f["/etc/systemd/system/snowgloves-omniroute.service"]
    assert "Environment=OMNIROUTE_SERVER_HOST=127.0.0.1" in unit and "User=omniroute" in unit
    assert "temperance" not in rendered["text"].lower()
    caddy = f["/etc/caddy/Caddyfile"]
    assert "reverse_proxy 127.0.0.1:20128" in caddy and "flush_interval -1" in caddy
    assert "trusted_proxies static 173.245.48.0/20 2400:cb00::/32" in caddy
    assert "client_ip_headers CF-Connecting-IP" in caddy


def test_helper_scripts_are_valid_bash(rendered, tmp_path):
    for path, content in files(rendered["doc"]).items():
        if not path.startswith("/usr/local/sbin/"):
            continue
        script = tmp_path / Path(path).name
        script.write_text(content)
        proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{path}: {proc.stderr}"


def test_tailnet_join_consumes_its_key_and_serves_on_the_tailnet_only(rendered):
    script = files(rendered["doc"])["/usr/local/sbin/sg-gw-tailnet"]
    assert 'aws ssm delete-parameter --region eu-west-3 --name "$param"' in script
    assert "tailscale serve --bg --http 20128 http://127.0.0.1:20128" in script
    assert "--advertise-tags=tag:gateway" in script
