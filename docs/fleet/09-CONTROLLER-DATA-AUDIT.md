# Controller data integrity

Run the audit on the controller's private operations checkout. It reads source manifests and hashes bounded tenant-local files; it never ingests content, invokes providers, enables modules or changes files. Missing/unsafe sources remain visible holds. An explicitly excluded external capability remains outside tenant ingestion even when installed.

```sh
python3 scripts/fleet/source_audit.py --data-root /private/ops
```

Private scanner findings receive individual dispositions in a `snowgloves.controller-data-policy.v1` file. Each record binds a relative path and current SHA256 to `held-private`, `transfer: false`, `ingest: false` and its reason. Preserve original receipts; changed bytes require a new reviewed disposition. Historical redacted reports do not establish a false positive.

Before a future export, provide its exact relative candidate file list and the reviewed policy digest:

```sh
python3 scripts/fleet/source_audit.py --data-root /private/ops \
  --policy /private/ops/.planning/controller-data-policy.json \
  --policy-digest REVIEWED_SHA256 --candidate-list /private/candidates.json
```

The preflight rejects held paths, copies of the exact held bytes, hardlinks, symlinks and unsafe inputs. Exit0 means these specific checks passed; exit2 is a held source or rejected candidate, exit3 invalid/changed input. Passing does not grant transfer permission or constitute a general credential scan. Existing Git history is not rewritten, and arbitrary user copies are not intercepted. Transfer tooling must call this preflight before export; merely recording a policy file cannot enforce another program's behavior.

Coding01 verification: 11 tenants, 18 source records and 89 admitted files; no unexpected holds. Four original scanner-held receipts are individually checksum-bound and excluded. The original archive checksum/exclusions and current ingestion exclusion were verified; an actual candidate list containing all four was refused. The stale HeyZack external skill reference was rebound while `ingest: false` stayed unchanged. Full onboarding/team/device/RBAC/vault, other-node, recovery and capacity acceptance remain separate.
