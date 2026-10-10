#!/usr/bin/env python3
"""Read-only stdio MCP server for ONE tenant vault domain. Safe tools only: counts, masked samples and accounts,
suppression and IBAN-match checks. There is deliberately no reveal and no export tool; those stay human CLI actions."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.tenant_vault import Vault  # noqa: E402


def create_server(vault):
    from mcp.server import MCPServer
    text = lambda value: json.dumps(value, indent=2, ensure_ascii=False)
    mcp = MCPServer('snowgloves-vault-' + vault.domain, instructions=(
        'Restricted %s data for the tenant. Values are masked; full IBANs and address lists are never returned here. '
        'Use counts and samples to plan; a human performs reveals and exports.' % vault.domain))
    if vault.domain == 'marketing':
        @mcp.tool()
        def marketing_segments(tenant: str | None = None) -> str:
            """Contacts per segment: total, suppressed, reachable."""
            return text(vault.segment_counts(tenant))

        @mcp.tool()
        def marketing_sample(segment: str, limit: int = 10) -> str:
            """A few masked reachable contacts of a segment (capped at 25)."""
            return text(vault.sample(segment, limit))

        @mcp.tool()
        def marketing_is_suppressed(email: str) -> str:
            """Whether an address is on the do-not-contact list."""
            return text({'suppressed': vault.is_suppressed(email)})
    else:
        @mcp.tool()
        def finance_accounts() -> str:
            """Bank accounts per entity with bank, BIC and a masked IBAN."""
            return text(vault.accounts())

        @mcp.tool()
        def finance_entities() -> str:
            """Legal entities with SIREN and VAT numbers."""
            return text(vault.entities())

        @mcp.tool()
        def finance_verify_iban(entity: str, iban: str) -> str:
            """True when the entity has an account with exactly this IBAN; never reveals a stored value."""
            return text({'match': vault.verify_iban(entity, iban)})
    return mcp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True)
    parser.add_argument('--domain', required=True, choices=('finance', 'marketing'))
    args = parser.parse_args()
    try:
        server = create_server(Vault(args.vault, args.domain))
    except ImportError:
        print('The mcp package is required; run this with the Hermes Python environment.', file=sys.stderr)
        return 1
    asyncio.run(server.run_stdio_async())
    return 0


if __name__ == '__main__':
    sys.exit(main())
