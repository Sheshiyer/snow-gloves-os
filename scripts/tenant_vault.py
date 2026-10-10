#!/usr/bin/env python3
"""Operator CLI for the tenant vaults (see lib/tenant_vault.py). Reveal and export are explicit, logged, human actions."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.tenant_vault import Vault, VaultError  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True, help='path to the vault file (0600, in a 0700 directory outside any git repo)')
    parser.add_argument('--domain', required=True, choices=('finance', 'marketing'))
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('ingest-bank'); p.add_argument('--tenant', required=True); p.add_argument('--file', required=True)
    p = sub.add_parser('ingest-contacts'); p.add_argument('--tenant', required=True); p.add_argument('--contacts', required=True); p.add_argument('--suppression')
    p = sub.add_parser('link-erp'); p.add_argument('--tenant', required=True); p.add_argument('--accounts', required=True); p.add_argument('--snapshot', default='')
    sub.add_parser('accounts'); sub.add_parser('entities'); sub.add_parser('segments')
    p = sub.add_parser('audit'); p.add_argument('-n', type=int, default=20)
    p = sub.add_parser('reveal'); p.add_argument('--id', type=int, required=True); p.add_argument('--actor', required=True); p.add_argument('--reason', required=True)
    p = sub.add_parser('export'); p.add_argument('--segment', required=True); p.add_argument('--dest', required=True); p.add_argument('--actor', required=True); p.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    try:
        vault = Vault(args.vault, args.domain)
        c = args.command
        if c == 'ingest-bank':
            result = vault.ingest_bank_markdown(args.tenant, Path(args.file).read_text(encoding='utf-8', errors='replace'), Path(args.file).name)
        elif c == 'ingest-contacts':
            result = vault.ingest_contacts(args.tenant, args.contacts, args.suppression, Path(args.contacts).name)
        elif c == 'link-erp':
            result = vault.link_erp(args.tenant, args.accounts, args.snapshot, Path(args.accounts).name)
        elif c == 'accounts':
            result = vault.accounts()
        elif c == 'entities':
            result = vault.entities()
        elif c == 'segments':
            result = vault.segment_counts()
        elif c == 'audit':
            result = vault.audit_tail(args.n)
        elif c == 'reveal':
            print(vault.reveal_iban(args.id, args.actor, args.reason))
            return 0
        else:
            result = {'rows': vault.export_segment(args.segment, args.dest, args.actor, args.reason)}
    except (VaultError, OSError) as error:
        print('vault: %s' % error, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
