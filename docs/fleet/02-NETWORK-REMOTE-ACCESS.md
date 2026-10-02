# 02. Network and remote access: Tailscale, Remote Management, SSH

Steps 2 and 3 of the [README](README.md). Tailscale carries every machine-to-machine connection
(Screen Sharing, Apple Remote Desktop, SSH, the gateway). Cloudflare Access stays for browser
dashboards only. This supersedes the "Cloudflare Tunnel plus Access for everything" stance in
`docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md`: VNC and SSH through Access need `cloudflared` on every
client Mac, which is one more daemon per person for no gain once a tailnet exists.

## Tailscale on each mini

The overlay name of each mini is its `overlay` value in `fleet.yaml` (`marketing-mac`,
`design-mac`, `coding-mac`); MagicDNS makes those names resolve from every device on the tailnet.

```bash
brew install tailscale                 # open-source tailscaled + CLI, runs as a LaunchDaemon
sudo brew services start tailscale     # starts at boot, before anyone logs in
sudo tailscale up --operator="$USER"   # browser login with the company Tailscale account
sudo tailscale set --hostname <wing>-mac
tailscale status                       # the mini should list itself as <wing>-mac
```

Why the daemon and not the App Store app: the GUI app only runs once a user is logged in. After a
reboot of the Coding Mac nobody is logged in, and you need the login window reachable over Screen
Sharing to log `sg-coding` in remotely. If Homebrew offers both, the GUI cask is named `tailscale-app`
on current Homebrew (`tailscale` on older ones); check `brew search tailscale` and
tailscale.com/kb for the current macOS variant matrix before mixing them.

Team Macs install the normal Tailscale app and sign in with their own login.

Key expiry: the Coding Mac is always on and must never drop off the tailnet because a key aged out.
In the Tailscale admin console open the machine `coding-mac` and choose **Disable key expiry**. Do
the same for the other two minis; tag them (below) so the ACL applies.

## ACL sketch

Tags: `tag:wing-marketing`, `tag:wing-design`, `tag:wing-coding` for the minis, `tag:team` for
staff Macs, `tag:admin` for the founder's Mac (Remote Desktop also needs 3283). Paste into the
tailnet policy file and adjust `tagOwners` to the real admin login.

```json
{
  "tagOwners": {
    "tag:admin":          ["autogroup:admin"],
    "tag:team":           ["autogroup:admin"],
    "tag:wing-marketing": ["autogroup:admin"],
    "tag:wing-design":    ["autogroup:admin"],
    "tag:wing-coding":    ["autogroup:admin"]
  },
  "acls": [
    // team Macs: Screen Sharing and SSH to every wing
    {"action": "accept", "src": ["tag:team", "tag:admin"],
     "dst": ["tag:wing-marketing:5900,22", "tag:wing-design:5900,22", "tag:wing-coding:5900,22"]},
    // founder's Apple Remote Desktop: reporting channel
    {"action": "accept", "src": ["tag:admin"],
     "dst": ["tag:wing-marketing:3283", "tag:wing-design:3283", "tag:wing-coding:3283"]},
    // gateway and Hermes: wings reach the Coding Mac only
    {"action": "accept", "src": ["tag:wing-marketing", "tag:wing-design", "tag:wing-coding"],
     "dst": ["tag:wing-coding:20128,4100"]}
  ]
}
```

Nothing else is open. No wing can reach another wing's 5900 or 22; a team Mac cannot reach
20128 (a runtime on a laptop that needs the gateway is a separate decision in
[04-GATEWAY.md](04-GATEWAY.md)).

## Remote Management (ARD) and Remote Login (SSH)

Both are enabled by the script; it prints first and changes nothing without `--apply`.

```bash
bash scripts/fleet/remote_access.sh --wing <wing>            # dry-run
sudo bash scripts/fleet/remote_access.sh --wing <wing> --apply
```

What it runs, so you can do it by hand in System Settings instead:

| Setting | System Settings | CLI the script runs |
|---|---|---|
| Remote Management on, for `sg-admin` and `sg-<wing>`, all privileges | General > Sharing > Remote Management > (i) > users | `kickstart -activate -configure -access -on -users sg-admin,sg-<wing> -privs -all -restart -agent -menu` |
| Remote Login on, limited to the two users | General > Sharing > Remote Login > (i) > Only these users | `systemsetup -setremotelogin on` then `dseditgroup -o edit -a <user> -t user com.apple.access_ssh` |
| Never sleep, restart after power failure, wake on LAN | Energy | `pmset -a sleep 0 displaysleep 10 autorestart 1 womp 1` |

Known edge: on macOS 10.14 and later Apple documents that `kickstart` cannot turn Remote
Management on for the very first time on a machine. If the ARD step reports no change, flip the
toggle once in System Settings, then rerun the script; `kickstart` then manages users and
privileges. Check `man kickstart` or Apple's kickstart support article for the current wording.

Remote Management includes Screen Sharing. Once it is on, the separate Screen Sharing toggle is
greyed out with a note that Remote Management controls it; that is expected.

## The founder: Apple Remote Desktop

Install Apple Remote Desktop (paid, Mac App Store, company Apple Account) on the founder's Mac.
Then:

1. Scanner > Network Address, or add by name: `marketing-mac`, `design-mac`, `coding-mac` (MagicDNS).
2. Authenticate as `sg-admin` once per machine; the credential sits in the ARD database, not in a file.
3. Observe or Control a wing from the toolbar; Curtain mode is not needed in a shared office.
4. Manage > Send UNIX Command, run as user `sg-<wing>`, to all three minis:

```bash
cd ~/snow-gloves-os && make fleet-doctor
```

Send UNIX Command is the only fleet-wide command path; everything else is per machine. Treat it as
read-only in practice (doctor, status, `tailscale status`) and do changes machine by machine.

## The team: Screen Sharing and SSH

Built in, nothing to install. From a team Mac on the tailnet:

```bash
bash scripts/fleet/connect.sh coding            # open vnc://sg-coding@coding-mac
bash scripts/fleet/connect.sh coding ssh        # ssh sg-coding@coding-mac
```

The script only reads `fleet.yaml`; the equivalent by hand is `open vnc://sg-coding@coding-mac`
and `ssh sg-coding@coding-mac`. First SSH login: add your public key as described in
[06-TEAM-ACCESS.md](06-TEAM-ACCESS.md), after that no password prompt.

## Cloudflare Access

Remains in front of browser dashboards (the catalog site, any future fleet dashboard from
`docs/FLEET-CONTROL-PLANE-PLAN.md`). It is not used for ARD, Screen Sharing or SSH and the minis
run no `cloudflared` for that purpose.

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `connect.sh` says host not found or times out | `tailscale status` on your Mac and on the wing | both must show the wing online; `sudo tailscale up` on the wing; MagicDNS on in the admin console |
| Connection refused on 5900 | Remote Management is off | `remote_access.sh --wing <wing> --apply` or System Settings > Sharing |
| Screen Sharing toggle greyed out in System Settings | Remote Management is on and owns it | expected; add the user under Remote Management > (i) instead |
| Screen Sharing connects, login rejected | user not in the Remote Management list | rerun the `kickstart` step, or tick the user in Sharing > Remote Management |
| Asks for a password every time | you are typing the operator password, not using a key | `ssh-copy-id sg-<wing>@<wing>-mac`; for Screen Sharing tick "Remember password in my keychain" on your own Mac |
| SSH works, Screen Sharing does not | ACL allows 22 but not 5900 | check the `dst` ports in the policy file |
| Coding Mac vanished after a reboot | stuck at FileVault unlock, or key expired | someone in Paris unlocks; confirm key expiry is disabled |
| Wing cannot reach `coding-mac:20128` | ACL or OmniRoute down | `curl -s http://coding-mac:20128/healthz` from the wing; then [07-OPERATIONS.md](07-OPERATIONS.md) |
