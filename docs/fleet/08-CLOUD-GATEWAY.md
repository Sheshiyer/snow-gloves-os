# 08. Cloud gateway: OmniRoute on EC2 behind Cloudflare

An alternative to [04-GATEWAY.md](04-GATEWAY.md)'s Coding Mac host. One OmniRoute instance runs on a small EC2
instance with an Elastic IP in the company's AWS account. Cloudflare, in the company's own Cloudflare account,
fronts it at `https://gw.<company-zone>`. Every wing uses that URL. The tailnet stays as the admin path and the
fallback route.

Which accounts, zone and IPs an instance uses is private and lives in the data checkout's `fleet.yaml`
(`cloud_gateway:` block). This repo holds only the code.

## Topology

```
 wing Macs, team laptops  ── Claude Code / Codex / Grok / OpenCode ──  https://gw.<zone>  + scoped key
        │
        ▼  Cloudflare (company account, one zone)
           WAF      /v1/* and /healthz only from the office egress IPs
           Access   everything else (dashboard, management API) needs an allowed email
        │  443, origin = Elastic IP, Full (strict) with an Origin CA certificate
        ▼
 EC2 (Ubuntu 24.04 arm64, t4g.medium), security group: 443 from Cloudflare ranges, 41641/udp, no SSH
   caddy :443  ──►  127.0.0.1:20128  snowgloves-omniroute (systemd, data /var/lib/omniroute/.omniroute)
   tailscale   joins the company tailnet as tag:gateway; `tailscale serve` exposes :20128 on the tailnet only
   backups     nightly sqlite .backup + .env → private S3 bucket (versioned, KMS); 7 daily EBS snapshots
```

The Elastic IP is two things: the fixed origin behind Cloudflare, and the single stable egress IP every
provider sees.

## Keep it apart from any personal setup

Snow Gloves is the company's system. If the operator also runs a personal gateway (their own OmniRoute on their
Mac, their own Cloudflare zones and AWS profiles), none of it may be reused here. These guards enforce that:

| Guard | Where |
|---|---|
| Gateway hostnames must sit under `cloud_gateway.zone` and under none of `deny_domains`. The AWS profile must be named, and not `default` or anything in `deny_aws_profiles` | `doctor.py` check `fleet-boundary` (critical when the block exists) |
| `aws sts get-caller-identity` must equal `aws_account_id`. The Cloudflare token must read `cf_zone_id`, which must be named `zone` and owned by `cf_account_id` | `scripts/fleet/cloud_guard.py check` |
| Every infra command runs the guard first and stops on any failure | `scripts/fleet/cloud_gateway.sh` |
| The Cloudflare stack refuses a hostname or zone under a denied domain | `infra/cloudflare-gateway` precondition |
| Nothing on the instance is named after the personal runtime, and the provider store starts empty (never a copy of a personal `~/.omniroute`) | `infra/aws-gateway/cloud-init.yaml.tftpl`, step 6 below |

## fleet.yaml

```yaml
gateway:
  kind: cloud
  port: 20128
  url: "https://gw.<zone>"               # clients
  tailnet_url: "http://<tailnet_hostname>:20128"   # fallback; gateway_client.py --via tailnet
cloud_gateway:
  name: snowgloves-gw                    # resource prefix and SSM path /<name>/...
  region: eu-west-3
  hostname: gw.<zone>
  zone: <zone>
  aws_profile: <company-profile>         # never `default`
  aws_account_id: "<12 digits>"
  cf_account_id: <cloudflare account id>
  cf_zone_id: <cloudflare zone id>
  cf_token_keychain: snowgloves-cloudflare            # Keychain service holding the scoped API token
  tailscale_authkey_keychain: snowgloves-tailscale-authkey
  tailnet_hostname: snowgloves-gw
  allow_ips: ["<office egress IP>"]
  access_emails: ["<operator email>"]
  alarm_email: "<ops email>"
  budget_alarm_usd: 60
  omniroute_version: "3.8.50"
  deny_domains: ["<personal zones and Access team names>"]
  deny_aws_profiles: ["<personal profiles>"]
```

## Bring-up

Steps 1 and 2 are done by a person in the AWS and Cloudflare consoles. The agent never types credentials.

1. **AWS.** Create an IAM Identity Center user with an admin permission set in the company account, then run
   `aws configure sso --profile <company-profile>` and `aws sso login --profile <company-profile>`.
2. **Cloudflare**, in the company account:
   - add the zone;
   - enable Zero Trust (the free plan is enough) for Access;
   - create an API token with:
     - Zone: DNS Edit, Zone Settings Edit, SSL and Certificates Edit, Firewall Services Edit, all on that zone only;
     - Account: Access Apps and Policies Edit;
   - store the token without it reaching shell history:
     `security add-generic-password -a snowgloves -s snowgloves-cloudflare -w`.
3. **Tailscale.** In the company tailnet's admin console:
   - create a single-use, pre-authorized auth key tagged `tag:gateway`;
   - store it with `security add-generic-password -a snowgloves -s snowgloves-tailscale-authkey -w`;
   - add an ACL rule allowing `tag:gateway:20128` from company devices only.
4. **Guard.** `bash scripts/fleet/cloud_gateway.sh guard` should print three `OK` lines.
5. **Provision**, with `SNOWGLOVES_DATA` pointing at the data checkout:
   ```bash
   bash scripts/fleet/cloud_gateway.sh bootstrap-state     # private, versioned, encrypted tofu state bucket
   bash scripts/fleet/cloud_gateway.sh aws plan            # read it
   bash scripts/fleet/cloud_gateway.sh aws apply
   bash scripts/fleet/cloud_gateway.sh cloudflare plan
   bash scripts/fleet/cloud_gateway.sh cloudflare apply    # DNS, Origin CA cert → SSM, WAF, Access
   bash scripts/fleet/cloud_gateway.sh tls-refresh         # instance installs the cert, caddy starts
   bash scripts/fleet/cloud_gateway.sh tailnet-join        # one-shot key → SSM → join → key deleted
   ```
6. **Providers.**
   - Open `https://gw.<zone>/dashboard`, which asks for the Access email code.
   - Set the dashboard password first.
   - Add API-key providers.
   - Sign in to account providers only for accounts the company is entitled to use from a server. Sign-ins from a
     datacenter IP are challenged more often than office sign-ins; check each provider's terms.
   - Recreate the combos. Never restore a personal gateway's database here.
7. **Keys.** Mint one scoped key per machine and per person. Set `allowed_endpoints = ["chat","models"]`, that
   wing's combos, a daily limit, and `ip_allowlist` = the office egress IP. Caddy passes Cloudflare's
   `CF-Connecting-IP` as the client IP.
8. **Clients**, on each wing:
   ```bash
   python3 scripts/fleet/gateway_client.py set-url --url https://gw.<zone> --key-ref keychain:snowgloves-gateway-<wing>          # dry-run
   python3 scripts/fleet/gateway_client.py set-url --url https://gw.<zone> --key-ref keychain:snowgloves-gateway-<wing> --apply
   python3 scripts/fleet/gateway_client.py doctor --key-ref keychain:snowgloves-gateway-<wing>    # tailscale is optional for an https gateway
   ```
   Fallback when Cloudflare is down, or for a non-streaming call longer than Cloudflare's 100-second limit:
   `set-url --via tailnet ...` points the surfaces at `http://<tailnet_hostname>:20128`.

## Verify

| Claim | Proof |
|---|---|
| The right accounts | `cloud_gateway.sh guard` prints three OK lines |
| Only Cloudflare reaches the origin | `curl -m 5 https://<elastic-ip>` from outside times out |
| OmniRoute is not on a public interface | over Tailscale SSH: `ss -ltnp \| grep 20128` shows `127.0.0.1` (and `tailscale serve`) only |
| The edge rules work | from outside the office, `/v1/models` returns 403; `/dashboard` asks for the Access code |
| The gateway serves | from the office, `curl -H "Authorization: Bearer $KEY" https://gw.<zone>/v1/models` returns 200, and a streaming Claude Code / Codex call completes |
| Egress is the static IP | on the instance, `curl -s https://checkip.amazonaws.com` equals the Elastic IP |
| Backups restore | `cloud_gateway.sh backup-now`, then restore the archive on a fresh instance and `/v1/models` answers |

## Operate

- **Backups.** Nightly at 02:00 UTC to `s3://<name>-backups-<account>/backups/` (35 days), plus 7 daily EBS
  snapshots. The archive holds the storage key (`.env`), so the bucket is private, versioned and KMS-encrypted.
- **Alarms.** A failed host check triggers EC2 auto-recover, and a failed OS check triggers a reboot. Both email
  `alarm_email`, as does the monthly budget at 100% actual or forecast.
- **Upgrades.** Bump `omniroute_version` in fleet.yaml. On the instance, run
  `sudo npm i -g omniroute@<v> && sudo systemctl restart snowgloves-omniroute`. Take a snapshot first.
- **Rollback.** Point clients back at the Mac gateway with `set-url --host <mac> --port 20128`.
  `cloud_gateway.sh cloudflare destroy` then `aws destroy` removes everything. The backups bucket refuses to
  delete while it holds objects, which is intended.
