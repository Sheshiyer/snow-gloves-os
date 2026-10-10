#!/usr/bin/env python3
"""PreToolUse guard: the ERP MCP server (id 6e66be5a-...) may only be READ, ids-only.

Blocks (exit 2) every tool of that server except execute_read_only_query, and re-validates that tool's SQL with the
fleet's own validator plus a deny list of never-touch tables and personal/bank columns. Fails closed: if this guard
cannot run its checks it blocks. Receipt: snow-gloves-ops specs/ai-commercial-organization/erp-binding.json.
"""
import json
import os
import re
import sys

SERVER = 'mcp__6e66be5a-d0cb-4df1-8fd4-bbfaf77c8604__'
READ_TOOL = SERVER + 'execute_read_only_query'
LIB = os.environ.get('SNOWGLOVES_SCRIPTS') or os.path.expanduser('~/Projects/snow-gloves-os/scripts')
BINDING = os.environ.get('SNOWGLOVES_ERP_BINDING') or os.path.expanduser('~/Projects/snow-gloves-ops/specs/ai-commercial-organization/erp-binding.json')
FALLBACK_COLUMNS = ['cli_bank_iban', 'cli_bank_bic', 'cli_bank_name', 'cli_bank_account_holder', 'cli_bank_address', 'cli_email', 'cli_accounting_email',
                    'cli_newsletter_email', 'cli_tel1', 'cli_tel2', 'cli_cellphone', 'cli_fax', 'cli_address1', 'cli_address2', 'cli_first_name',
                    'cli_last_name', 'cli_notes', 'cli_comment_for_client', 'cli_comment_for_interne', 'cli_credit_limit', 'cli_discount']
FALLBACK_TABLES = ['TM_MAK_Mcp_Api_Key', 'TR_BAC_Bank_Account']


def block(reason):
    sys.stderr.write('ERP read-only guard: %s\n' % reason)
    sys.exit(2)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        block('could not read the tool call, refusing')
    name = event.get('tool_name') or ''
    if not name.startswith(SERVER):
        return 0
    if name != READ_TOOL:
        block('%s is not permitted. This ERP is read-only; only execute_read_only_query may be used.' % name.replace(SERVER, ''))
    sql = (event.get('tool_input') or {}).get('query')
    if not isinstance(sql, str):
        block('execute_read_only_query needs a query string')
    try:
        sys.path.insert(0, LIB)
        from lib.erp_reader import ErpQueryError, validate_query
    except Exception:
        block('the SQL validator is unavailable, refusing (fail closed)')
    try:
        validate_query(sql, 100)
    except ErpQueryError as error:
        block('query rejected: %s' % error)
    try:
        binding = json.load(open(BINDING))
        columns, tables = binding.get('never_select', FALLBACK_COLUMNS), binding.get('never_touch_tables', FALLBACK_TABLES)
    except (OSError, ValueError):
        columns, tables = FALLBACK_COLUMNS, FALLBACK_TABLES
    lowered = re.sub(r"'(?:[^']|'')*'", "''", sql).lower()
    for table in tables:
        if re.search(r'\b%s\b' % re.escape(table.lower()), lowered):
            block('table %s must never be touched' % table)
    for column in columns:
        if re.search(r'\b%s\b' % re.escape(column.lower()), lowered):
            block('column %s is personal or bank data and is not approved' % column)
    if re.search(r'select\s+(distinct\s+)?\*', lowered) or re.search(r',\s*\*\s*(from|,)', lowered) or re.search(r'\.\*', lowered):
        block('SELECT * is not allowed; name the columns (ids only)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
