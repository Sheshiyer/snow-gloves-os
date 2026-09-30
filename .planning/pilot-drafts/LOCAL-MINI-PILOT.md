# Draft one Mac mini local pilot — 1 October 2026

**Implementation pending. These commands specify the acceptance target; they are not available yet.**

This kit installs the local bootstrap and recovery CLI. Its Python entry path
uses only the standard library and requires **Python 3.10 or later**. It does not
install the full business-operations runtime. Live identity, vault enrollment,
providers, remote access, supervised services, and physical acceptance remain held.

## Prepare the mini

Use a local directory outside iCloud synchronization. Record the mini's chip,
RAM, macOS version, disk capacity, and the operator who will run this pilot.
Have a working Python 3.10+ interpreter available, then copy the reviewed
`snowgloves-local-pilot.tar.gz` bundle and its adjacent SHA256 checksum to the mini.

Verify the outer checksum before unpacking, then verify the file manifest:

```bash
shasum -a 256 -c snowgloves-local-pilot.tar.gz.sha256
mkdir snowgloves-local-pilot
tar -xzf snowgloves-local-pilot.tar.gz -C snowgloves-local-pilot
cd snowgloves-local-pilot
python3 scripts/package_pilot.py --verify .
```

The checksum detects changed bytes; it does not establish signer identity.
Receive this exact kit through the existing trusted operator channel. The pilot
does not claim signed device enrollment or signed cross-runtime handoff.

## Install into a dedicated directory

```bash
bash scripts/install-local.sh --prefix "$HOME/SnowGlovesPilot" --dry-run
bash scripts/install-local.sh --prefix "$HOME/SnowGlovesPilot"
cd "$HOME/SnowGlovesPilot"
./bin/snowgloves --version
./bin/snowgloves node inspect --root . > inspect.json
./bin/snowgloves node plan --root . --node mini-01 > plan.json
python3 -m json.tool plan.json
```

Review the three file paths, their contents, the source digest, and held reasons
before apply. Planning writes no node state: the JSON redirection above is the
operator's output file, outside the CLI's mutation journal.

```bash
PLAN_DIGEST=$(python3 -c 'import json; print(json.load(open("plan.json"))["digest"])')
./bin/snowgloves node apply --plan plan.json --digest "$PLAN_DIGEST"
./bin/snowgloves node status --root .
./bin/snowgloves node resume --plan plan.json --digest "$PLAN_DIGEST"
./bin/snowgloves node apply --plan plan.json --digest "$PLAN_DIGEST"
./bin/snowgloves node doctor --root . > doctor.json
./bin/snowgloves node debug collect --root . > debug.json
```

Exit codes: **0** means this local operation succeeded; **1** means a mandatory
local check failed; **2** means held requirements, drift, a lock, or manual
recovery; **3** means invalid invocation/data. A configured pilot deliberately
keeps `profile_ready=false`. Doctor exits **2** while the live requirements are
unverified. Capture that result and continue the local pilot; do not relabel it
as fleet or production readiness.

## Recovery acceptance on the mini

1. Run apply twice. Confirm there are no duplicate effects and existing receipts remain bound to the same plan.
2. Run resume and confirm completed files are freshly checked.
3. Reboot the mini, reopen the same directory, and run status, resume, and doctor. Capture the outputs as physical-device evidence; the CLI is not a daemon.
4. Copy the pilot directory to a separate local backup, restore that copy to a disposable directory, and inspect its journal and files. A plan binds its root: do not silently apply a plan from a different path.
5. Demonstrate rollback with the original reviewed digest:

   ```bash
   ./bin/snowgloves node rollback --plan plan.json --digest "$PLAN_DIGEST"
   ./bin/snowgloves node status --root .
   ```

6. In a separate disposable pilot directory, edit one owned file after apply. Rollback must preserve the edit and report manual recovery. Do not perform this destructive test on meaningful configuration.

The source suite exercises interrupted writes and lock contention with synthetic
fixtures. Record real interruption and recovery evidence on the mini if required
for acceptance; synthetic success does not prove the OS survived a power loss.

Rollback retains its journal for inspection. It cannot uninstall Python or the
copied CLI package, and it never acts on tenant files or host runtime configuration.
Keep the package until the pilot evidence is reviewed.

## Return the installation receipt

Return the bundle checksum, CLI source digest, mini hardware inventory, selected
node alias, apply/resume/status outputs, doctor exit code, rollback result, and
reboot/restore observations. Keep debug output redacted and do not attach
environment dumps, native login stores, tokens, or contact exports.

Only promote the pilot after the physical evidence is reviewed. The next
separate implementation lanes are verified identity/policy, device/vault trust,
services/private transport, and fleet/session infrastructure.
