#!/usr/bin/env python3
"""Check the vault's ERP references against the live ERP, read-only and only when the contract is admitted.

  erp_verify_links.py --contract C.json --binding B.json --status
  erp_verify_links.py --contract C.json --binding B.json --vault V --tenant T --actor NAME --transport pkg.module:function

The transport is a Python callable `call(tool, arguments) -> dict` that talks to the erp_axtech MCP endpoint with
the per-brand credential. It is deliberately not part of this repository.
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.erp_reader import ErpGateError, ErpQueryError, ErpReader, verify_links  # noqa: E402
from lib.tenant_vault import Vault, VaultError  # noqa: E402


def unmet_gates(contract, binding):
    try:
        ErpReader(lambda *a: None, contract, binding)._gate()
        return []
    except ErpGateError as error:
        return str(error).split('; ')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--contract', required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--status', action='store_true', help='print the unmet gates and exit')
    parser.add_argument('--vault'); parser.add_argument('--tenant'); parser.add_argument('--actor')
    parser.add_argument('--transport', help='module:function providing call(tool, arguments)')
    args = parser.parse_args(argv)
    try:
        contract = json.loads(Path(args.contract).read_text())
        binding = json.loads(Path(args.binding).read_text()) if Path(args.binding).exists() else {}
    except (OSError, ValueError) as error:
        print('Cannot read the contract or binding: %s' % error, file=sys.stderr)
        return 2
    unmet = unmet_gates(contract, binding)
    if args.status:
        print(json.dumps({'ready': not unmet, 'unmet': unmet, 'required_before_live_use': contract.get('required_before_live_use', [])}, indent=1))
        return 0 if not unmet else 3
    if unmet:
        print('Blocked by the contract: %s' % '; '.join(unmet), file=sys.stderr)
        return 3
    if not (args.vault and args.tenant and args.actor and args.transport):
        parser.error('--vault, --tenant, --actor and --transport are required to run')
    module, _, function = args.transport.partition(':')
    try:
        call = getattr(importlib.import_module(module), function)
        result = verify_links(Vault(args.vault, 'marketing'), ErpReader(call, contract, binding), args.tenant, args.actor)
    except (ImportError, AttributeError, ErpGateError, ErpQueryError, VaultError) as error:
        print('Cannot verify: %s' % error, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
