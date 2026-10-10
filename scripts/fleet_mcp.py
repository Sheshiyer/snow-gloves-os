#!/usr/bin/env python3
"""Stdio MCP server for the Snow Gloves fleet coordinator.

Run it on Coding 01 and reach it from any Hermes (or other MCP) client over SSH, e.g.
    hermes mcp add snowgloves-fleet --command ssh --args coding-01-tailnet '~/.local/bin/snowgloves-fleet-mcp'
It is a thin client: the coordinator still owns authentication, project scope, write gating and
the task graph. The operator token is read on this machine and never leaves it.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

TASK_ID = re.compile(r'[a-f0-9]{32}')


class FleetError(Exception):
    """The coordinator refused or could not serve a request; the message is safe to show."""


class FleetApi:
    def __init__(self, endpoint, token):
        parts = urlsplit(endpoint)
        if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost') or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('The coordinator endpoint must be plain loopback http')
        if not token.strip() or '\n' in token or '\r' in token:
            raise ValueError('A valid operator token is required')
        self.endpoint, self._token = endpoint.rstrip('/'), token.strip()

    def call(self, method, path, body=None):
        request = urllib.request.Request(self.endpoint + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=100) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                reason = json.loads(error.read(2048)).get('error')
            except (ValueError, AttributeError):
                reason = None
            raise FleetError('Coordinator refused the request (HTTP %d)%s' % (error.code, ': ' + reason if isinstance(reason, str) else '')) from None
        except (urllib.error.URLError, OSError, ValueError):
            raise FleetError('Fleet coordinator unavailable') from None

    @staticmethod
    def _id(task_id):
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise ValueError('task_id must be a 32-character lowercase hex id')
        return task_id

    def list(self):
        return self.call('GET', '/v1/tasks')['tasks']

    def status(self, task_id):
        return self.call('GET', '/v1/tasks/' + self._id(task_id))

    def logs(self, task_id):
        return self.call('GET', '/v1/tasks/%s/events' % self._id(task_id))['events']

    def cancel(self, task_id):
        return self.call('POST', '/v1/tasks/%s/cancel' % self._id(task_id), {})

    def fanout(self, task_id):
        return self.call('POST', '/v1/tasks/%s/fanout' % self._id(task_id), {})

    def submit(self, project, brief, title=None, category='development', runtime='codex', idempotency_key=None,
               parent_id=None, logical_role=None, stage=None, supersedes=None, access=None, worker_id=None):
        body = dict(project=project, brief=brief, category=category, runtime=runtime, idempotency_key=idempotency_key or uuid.uuid4().hex)
        optional = dict(title=title, parent_id=parent_id, logical_role=logical_role, stage=stage, supersedes=supersedes, access=access, worker_id=worker_id)
        body.update({key: value for key, value in optional.items() if value is not None})
        result = self.call('POST', '/v1/tasks', body)
        return result.get('task', result)


    def context(self):
        return self.call('GET', '/v1/context')

    def capabilities(self):
        return self.call('GET', '/v1/capabilities')['capabilities']

    def approvals(self):
        return self.call('GET', '/v1/approvals')['approvals']

    def artifact(self, task_id):
        return self.call('GET', '/v1/tasks/%s/artifact' % self._id(task_id))['artifact']

    def execute_capability(self, project, capability_id, inputs, idempotency_key, approval_id=None, worker_id=None):
        body = dict(project=project, capability_id=capability_id, inputs=inputs, idempotency_key=idempotency_key)
        body.update({key: value for key, value in dict(approval_id=approval_id, worker_id=worker_id).items() if value is not None})
        return self.call('POST', '/v1/capabilities/execute', body)

    def request_approval(self, project, capability_id, inputs, idempotency_key, worker_id=None):
        body = dict(project=project, capability_id=capability_id, inputs=inputs, idempotency_key=idempotency_key)
        if worker_id is not None:
            body['worker_id'] = worker_id
        return self.call('POST', '/v1/approvals', body)

    def decide_approval(self, approval_id, approve):
        return self.call('POST', '/v1/approvals/%s/%s' % (self._id(approval_id), 'approve' if approve else 'reject'), {})


def create_server(api):
    from mcp.server import MCPServer
    mcp = MCPServer('snowgloves-fleet', instructions=(
        'Snow Gloves fleet coordinator on Coding 01. Submit read-only development tasks, follow their status and logs, '
        'and build a task graph with parent_id/logical_role/stage. Retry a failed child with supersedes. '
        'Write access is refused unless the coordinator has enabled it for a CTO graph child.'))

    def text(value):
        return json.dumps(value, indent=2)

    @mcp.tool()
    def fleet_list() -> str:
        """List managed fleet tasks in your authorized scope (newest first)."""
        return text(api.list())

    @mcp.tool()
    def fleet_status(task_id: str) -> str:
        """Get one task. A graph parent includes graph.children and a derived graph.status."""
        return text(api.status(task_id))

    @mcp.tool()
    def fleet_logs(task_id: str) -> str:
        """Get a task's events, including artifact receipts."""
        return text(api.logs(task_id))

    @mcp.tool()
    def fleet_cancel(task_id: str) -> str:
        """Cancel a task; cancelling a graph parent also cancels its open children."""
        return text(api.cancel(task_id))

    @mcp.tool()
    def fleet_fanout(task_id: str) -> str:
        """Ask the coordinator to plan one authorized set of read-only roles for a development root.
        The coordinator alone checks the current owner, submit permission and default-off admission."""
        return text(api.fanout(task_id))

    @mcp.tool()
    def fleet_submit(project: str, brief: str, title: str | None = None, parent_id: str | None = None,
                     logical_role: str | None = None, stage: str | None = None, supersedes: str | None = None,
                     access: str | None = None, idempotency_key: str | None = None, worker_id: str | None = None) -> str:
        """Submit a task. For a graph child pass parent_id with logical_role (ceo, cto, chief-of-staff,
        librarian, interpreter, dispatcher, sentinel) and optionally stage (plan, reference, review, dispatch,
        verify). To retry a failed child pass supersedes=<its id> with the same parent, role, stage and access.
        access='write' is only honoured for a CTO child when the coordinator enables it."""
        return text(api.submit(project, brief, title=title, parent_id=parent_id, logical_role=logical_role, stage=stage,
                               supersedes=supersedes, access=access, idempotency_key=idempotency_key, worker_id=worker_id))

    @mcp.tool()
    def fleet_context() -> str:
        """Show your authorized projects, configured workers, observed availability and permissions."""
        return text(api.context())

    @mcp.tool()
    def fleet_capabilities() -> str:
        """List catalog readiness for every authorized project. Visibility does not grant execution."""
        return text(api.capabilities())

    @mcp.tool()
    def fleet_artifact(task_id: str) -> str:
        """Retrieve a bounded verified task artifact with source digest and safely redacted JSON."""
        return text(api.artifact(task_id))

    @mcp.tool()
    def fleet_execute_capability(project: str, capability_id: str, inputs: dict, idempotency_key: str,
                                 approval_id: str | None = None, worker_id: str | None = None) -> str:
        """Execute a reviewed enabled capability. Reuse the same idempotency_key and inputs after a network error.
        Required approval must already be bound to these exact inputs; this tool cannot grant it."""
        return text(api.execute_capability(project, capability_id, inputs, idempotency_key, approval_id, worker_id))

    @mcp.tool()
    def fleet_approvals() -> str:
        """List approvals in your scope, with reviewed inputs and their binding digests."""
        return text(api.approvals())

    @mcp.tool()
    def fleet_request_approval(project: str, capability_id: str, inputs: dict, idempotency_key: str,
                               worker_id: str | None = None) -> str:
        """Request approval for an approval-required capability without dispatching it."""
        return text(api.request_approval(project, capability_id, inputs, idempotency_key, worker_id))

    @mcp.tool()
    def fleet_approve(approval_id: str) -> str:
        """Approve a reviewed action. Requires separately granted approve permission; identity comes from authentication."""
        return text(api.decide_approval(approval_id, True))

    @mcp.tool()
    def fleet_reject(approval_id: str) -> str:
        """Reject a pending or unconsumed approved action. Requires separately granted approve permission."""
        return text(api.decide_approval(approval_id, False))

    return mcp


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--endpoint', default='http://127.0.0.1:4101')
    parser.add_argument('--token-file')
    args = parser.parse_args()
    token = Path(args.token_file).read_text() if args.token_file else os.environ.get('SNOWGLOVES_FLEET_TOKEN', '')
    if not token.strip():
        parser.error('Set SNOWGLOVES_FLEET_TOKEN or --token-file')
    try:
        server = create_server(FleetApi(args.endpoint, token))
    except ImportError:
        print('The mcp package is required; run this with the Hermes Python environment.', file=sys.stderr)
        return 1
    asyncio.run(server.run_stdio_async())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
