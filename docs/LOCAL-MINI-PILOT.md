# Snow Gloves local mini pilot

This pilot creates three local configuration files under
`<root>/.snowgloves-local/`. It does not enroll a person or device, enable a
provider, start a service, configure a runtime, inspect network identity, or
declare a fleet member ready. Identity, vault, services, network, providers,
and physical acceptance remain held until independently verified.

The tools require macOS or Linux with Python 3.10 or newer and use only the Python standard
library. They make no network calls, install no dependencies, execute no
detected tools, and do not change shell profiles or operating system services.

## Verify and install

Review the source before building a package. In the source checkout, select a
new output directory whose parent already exists, then build and verify it:

```sh
python3 -B scripts/package_pilot.py --output /path/to/snow-gloves-pilot
python3 -B scripts/package_pilot.py --verify /path/to/snow-gloves-pilot
```

The build also produces `/path/to/snow-gloves-pilot.tar.gz`, containing the same
seven files. A checksum manifest detects changed bytes; establish the source's
provenance separately. If transferring the archive, unpack into a new directory
and verify that directory with the reviewed source verifier before installation.

Run the installer from the verified package directory. Preview, then install to
a new private prefix:

```sh
cd /path/to/snow-gloves-pilot
sh scripts/install-local.sh --prefix "$HOME/.local/snow-gloves" --dry-run
sh scripts/install-local.sh --prefix "$HOME/.local/snow-gloves"
SNOWGLOVES_CLI="$HOME/.local/snow-gloves/bin/snowgloves"
```

The installer verifies the complete package before writing. It refuses a
different existing prefix; repeating the command succeeds when the installed
files still match the verified package exactly. Add the installed `bin`
directory to a shell command path yourself if desired. Package and install
publication use an atomic no-clobber directory operation and fail closed on
platforms that do not provide one.

Use absolute normalized paths without symlink ancestors. The installed manifest
covers its five runtime files; the package manifest also covers the installer.
Failed publication preserves its private `.stage-*` directory for review.

## Inspect, plan, and review

Use an existing directory as the local root. Inspection reports the operating
system, machine, RAM and disk information, and whether selected tools are
present. It only checks tool paths; it never runs them.

```sh
"$SNOWGLOVES_CLI" node inspect --root /path/to/node-root
"$SNOWGLOVES_CLI" node plan --root /path/to/node-root --node pilot-a > plan.json
```

Review the plan JSON, including its node, root, source digest, three file
contents, held requirements, and plan digest. Keep the reviewed digest with
that plan. The digest binds the exact plan contents; the source digest binds
the version and bootstrap implementation files. Apply, resume, and rollback
refuse a plan whose source digest no longer matches the installed code.

## Apply and check

Pass the reviewed plan digest explicitly:

```sh
"$SNOWGLOVES_CLI" node apply --plan plan.json --digest REVIEWED_SHA256
"$SNOWGLOVES_CLI" node status --root /path/to/node-root
"$SNOWGLOVES_CLI" node doctor --root /path/to/node-root
"$SNOWGLOVES_CLI" node debug collect --root /path/to/node-root
```

Apply records local configuration only. If an operation is interrupted, use
`resume` with the same reviewed plan and digest. Doctor verifies the local
files and their journal receipts, then reports live requirements as held.
Debug emits an allowlisted inventory and digest references; it does not dump
environment variables or file contents.

```sh
"$SNOWGLOVES_CLI" node resume --plan plan.json --digest REVIEWED_SHA256
"$SNOWGLOVES_CLI" node rollback --plan plan.json --digest REVIEWED_SHA256
```

Exit status `0` means the requested local command completed. Status `1` means a
required local check failed. Status `2` means local setup is held on live
requirements or a safe operation could not continue because of drift or a
lock. Status `3` means arguments or data are invalid. A configured local
profile always reports `profile_ready: false` while live and physical gates
remain unverified.

Rollback preserves pre-existing files and the journal/ownership anchors. If a
target changes during rollback, the command holds for manual recovery and may
preserve the captured file under `.snowgloves-local/quarantine/`. Keep that
evidence and inspect the journal before any manual repair. Do not delete the
journal or claim that a held rollback completed. Process-interruption tests
prove local recovery; physical reboot, power-loss and backup restore require
their own device evidence.
