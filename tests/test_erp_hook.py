"""The Claude Code PreToolUse guard for the ERP MCP server: read-only, ids-only, fails closed."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'scripts' / 'hooks' / 'erp-read-only.py'
S = 'mcp__6e66be5a-d0cb-4df1-8fd4-bbfaf77c8604__'


def run(event, env=None):
    stdin = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True,
                          env={**os.environ, 'SNOWGLOVES_SCRIPTS': str(ROOT / 'scripts'), **(env or {})})


def read(sql):
    return {'tool_name': S + 'execute_read_only_query', 'tool_input': {'query': sql}}


@pytest.mark.parametrize('event', [
    {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}},
    {'tool_name': 'mcp__other__upsert_thing', 'tool_input': {}},
    read('SELECT "cli_id" FROM "TM_CLI_CLient" WHERE "cli_id" IN (5,7) LIMIT 100'),
    read("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' LIMIT 100"),
    read('SELECT column_name, data_type FROM information_schema.columns ORDER BY ordinal_position'),
])
def test_allowed(event):
    assert run(event).returncode == 0


@pytest.mark.parametrize('tool', ['upsert_client', 'delete_client', 'hard_delete_client', 'hard_delete_supplier_order', 'send_invoice', 'record_payment',
                                  'adjust_stock', 'transfer_stock', 'record_count', 'submit_feedback', 'upload_attachment', 'void_invoice', 'anything_new_the_server_adds'])
def test_every_other_tool_of_the_erp_server_is_blocked(tool):
    done = run({'tool_name': S + tool, 'tool_input': {}})
    assert done.returncode == 2 and 'read-only' in done.stderr


@pytest.mark.parametrize('sql', [
    'DELETE FROM x', 'UPDATE "TM_CLI_CLient" SET cli_id = 1', 'INSERT INTO x VALUES (1)', 'DROP TABLE x', 'SELECT 1; DROP TABLE x', 'SELECT 1 -- x',
    'SELECT "cli_id" FROM "TM_CLI_CLient" LIMIT 5000', 'SELECT "cli_id" FROM "TM_CLI_CLient" FOR UPDATE',
    'SELECT 1 FROM "TR_BAC_Bank_Account" LIMIT 1', 'SELECT 1 FROM "TM_MAK_Mcp_Api_Key" LIMIT 1',
    'SELECT cli_bank_iban FROM "TM_CLI_CLient" LIMIT 1', 'SELECT cli_email FROM "TM_CLI_CLient" LIMIT 1', 'SELECT cli_tel1 FROM "TM_CLI_CLient" LIMIT 1',
    'SELECT * FROM "TM_CLI_CLient" LIMIT 1', 'SELECT t.* FROM "TM_CLI_CLient" t LIMIT 1', 'SELECT cli_id, * FROM "TM_CLI_CLient" LIMIT 1',
])
def test_the_one_read_tool_is_still_constrained(sql):
    assert run(read(sql)).returncode == 2


def test_fails_closed_on_garbage_a_missing_query_and_a_missing_validator(tmp_path):
    assert run('not json').returncode == 2
    assert run({'tool_name': S + 'execute_read_only_query', 'tool_input': {}}).returncode == 2
    assert run(read('SELECT 1 LIMIT 1'), env={'SNOWGLOVES_SCRIPTS': str(tmp_path)}).returncode == 2


def test_the_deny_list_falls_back_to_a_built_in_one_when_the_binding_is_unreadable(tmp_path):
    env = {'SNOWGLOVES_ERP_BINDING': str(tmp_path / 'missing.json')}
    assert run(read('SELECT cli_bank_iban FROM "TM_CLI_CLient" LIMIT 1'), env=env).returncode == 2
    assert run(read('SELECT 1 FROM "TR_BAC_Bank_Account" LIMIT 1'), env=env).returncode == 2


def test_the_installed_user_hook_is_identical_to_the_repo_copy():
    installed = Path.home() / '.claude' / 'hooks' / 'erp-read-only.py'
    if not installed.exists():
        pytest.skip('hook not installed on this machine')
    assert installed.read_text() == HOOK.read_text()
