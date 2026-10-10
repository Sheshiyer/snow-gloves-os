"""Gated, read-only ERP reference reader. The reference contract is enforced here in code, not just documented:
an admitted contract, a single read tool, one bounded SELECT, identifiers from a verified binding, ids only.

It takes an injected `call(tool, arguments)` so the transport (the erp_axtech MCP endpoint and its per-brand
authentication) is provisioned separately; nothing here holds a credential or opens a connection.
"""
import re

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
FORBIDDEN = ('insert', 'update', 'delete', 'drop', 'alter', 'create', 'truncate', 'grant', 'revoke', 'replace', 'merge', 'call', 'exec', 'execute',
             'pragma', 'attach', 'detach', 'set', 'lock', 'into', 'outfile', 'dumpfile', 'load', 'handler', 'show', 'use')
HARD_CAP = 100
ERP_REF = re.compile(r'^erp_axtech:client:(\d+)$')


class ErpGateError(Exception):
    """The contract or binding does not permit a live read."""


class ErpQueryError(Exception):
    """A query or a response broke a rule."""


def validate_query(sql, max_rows=HARD_CAP):
    """Return the query only if it is a single bounded SELECT; add a LIMIT when absent."""
    max_rows = min(int(max_rows), HARD_CAP)
    text = (sql or '').strip()
    if not text:
        raise ErpQueryError('Empty query')
    masked = re.sub(r"'(?:[^']|'')*'", "''", text)
    if text.endswith(';'):
        text, masked = text[:-1].rstrip(), masked[:-1].rstrip()
    if ';' in masked:
        raise ErpQueryError('Only a single statement is allowed')
    if '--' in masked or '/*' in masked or '*/' in masked:
        raise ErpQueryError('Comments are not allowed')
    if not re.match(r'(?is)^\s*(select|with)\b', masked):
        raise ErpQueryError('Only SELECT queries are allowed')
    lowered = masked.lower()
    for word in FORBIDDEN:
        if re.search(r'\b%s\b' % word, lowered):
            raise ErpQueryError('Keyword not allowed: %s' % word)
    if re.search(r'\bfor\s+(update|share)\b', lowered):
        raise ErpQueryError('Locking reads are not allowed')
    limits = re.findall(r'\blimit\s+(\d+)(?:\s*,\s*(\d+))?', lowered)
    for first, second in limits:
        if int(second or first) > max_rows:
            raise ErpQueryError('LIMIT exceeds the %d-row cap' % max_rows)
    return text if limits else '%s LIMIT %d' % (text, max_rows)


class ErpReader:
    def __init__(self, call, contract, binding):
        self._call, self.contract, self.binding = call, contract or {}, binding or {}

    def _gate(self):
        unmet = []
        if self.contract.get('status') != 'admitted':
            unmet.append('contract status is %r, not admitted' % self.contract.get('status'))
        if self.contract.get('mutation_tools_enabled') is not False:
            unmet.append('mutation tools must be explicitly disabled')
        table, column, revision = (self.binding.get(k) for k in ('table', 'id_column', 'verified_revision'))
        if not (isinstance(table, str) and IDENT.match(table) and isinstance(column, str) and IDENT.match(column)):
            unmet.append('binding needs safe table and id_column identifiers')
        if not (isinstance(revision, str) and revision.strip()):
            unmet.append('binding has no verified schema revision')
        if unmet:
            raise ErpGateError('; '.join(unmet))

    @property
    def max_rows(self):
        return min(int(self.contract.get('max_rows', HARD_CAP)), HARD_CAP)

    def call_tool(self, name, arguments):
        """The only door to the transport: one read tool, never the excluded or any other tool."""
        self._gate()
        read_tool = self.contract.get('read_tool', 'execute_read_only_query')
        excluded = (self.contract.get('excluded_tool') or {}).get('name')
        if name != read_tool or name == excluded:
            raise ErpGateError('Tool not permitted: %s' % name)
        return self._call(name, arguments)

    def query(self, sql):
        response = self.call_tool(self.contract.get('read_tool', 'execute_read_only_query'), {'query': validate_query(sql, self.max_rows)})
        if not isinstance(response, dict) or response.get('success') is not True:
            raise ErpQueryError('ERP read failed: %s' % ((response or {}).get('error') if isinstance(response, dict) else 'bad response'))
        rows = response.get('rows')
        if not isinstance(rows, list) or len(rows) > self.max_rows or int(response.get('row_count', len(rows))) > self.max_rows:
            raise ErpQueryError('Response exceeds the row cap')
        if response.get('truncated'):
            raise ErpQueryError('Response was truncated; refusing a partial answer')
        return rows

    def existing_ids(self, ids):
        """Which of these ERP client ids exist. Selects the id column only."""
        clean = []
        for value in ids:
            if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
                raise ErpQueryError('ERP ids must be integers')
            clean.append(int(value))
        found, unique = set(), sorted(set(clean))
        self._gate()
        table, column = self.binding['table'], self.binding['id_column']
        for start in range(0, len(unique), self.max_rows):
            batch = unique[start:start + self.max_rows]
            rows = self.query('SELECT %s FROM %s WHERE %s IN (%s)' % (column, table, column, ','.join(str(i) for i in batch)))
            found.update(int(r[0]) for r in rows)
        return found


def verify_links(vault, reader, tenant, actor):
    """Confirm each linked ERP reference exists, recording the answer; contacts are never changed."""
    ids = {}
    for ref in vault.erp_refs(tenant):
        match = ERP_REF.match(ref)
        if match:
            ids[ref] = int(match.group(1))
    existing = reader.existing_ids(ids.values())  # the gate raises before anything is recorded
    results = {ref: (i in existing) for ref, i in ids.items()}
    vault.record_erp_checks(tenant, results, actor)
    confirmed = sum(results.values())
    return {'checked': len(results), 'confirmed': confirmed, 'missing': len(results) - confirmed}
