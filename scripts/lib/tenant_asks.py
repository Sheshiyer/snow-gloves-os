"""Derive founder asks from tenant files.

Pure read-only derivation: context `FILL:` lines become fact asks, the portfolio
proposal's open cross-brand flows become decision asks, unadmitted sources and
enabled mcp/connector modules become connect asks, an unfilled brand domain
becomes a website ask, and a missing Meristem source becomes a brand ask.

Ids are stable over the derivation key, so re-deriving after a data change keeps
answers attached only while the same ask still exists. Every read is bounded and
fails closed; a broken file hides only the asks it could have produced.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

ASK_KINDS: tuple[str, ...] = ('fact', 'decision', 'connect', 'website', 'brand')
ROLE_FOR_KIND: dict[str, str] = {
    'fact': 'librarian',
    'decision': 'chief-of-staff',
    'connect': 'dispatcher',
    'website': 'interpreter',
    'brand': 'interpreter',
}

MAX_ASKS = 400
MAX_TITLE = 160
MAX_SOURCE = 240  # the client's source limit
# Clients reject strings containing C0 control characters (or DEL); every
# emitted string is checked or normalized against this one pattern.
CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')
MAX_PROPOSED = 500
MAX_FILE_BYTES = 256 * 1024
PROPOSAL_MAX_BYTES = 512 * 1024
PROPOSAL_REL = Path('specs') / '006-editorial-steward-integration' / 'portfolio-map-proposal.json'

FILL_RE = re.compile(r'^\s*-?\s*FILL:\s*(.+)$')
ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')
SENSITIVE_RE = re.compile(r"(?i)(?:^|[^a-z0-9])(?:secret|password|passwd|credentials?|token|bearer)(?:$|[^a-z0-9])|api[_. -]?key|(?:^|[^a-z0-9])(?:sk-|ghp_|github_pat_)")


def ask_id(tenant: str, kind: str, key: str) -> str:
    return hashlib.sha256(f"{tenant}|{kind}|{key}".encode('utf-8')).hexdigest()[:32]


def load_proposal(data_root: Path) -> dict | None:
    path = Path(data_root) / PROPOSAL_REL
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > PROPOSAL_MAX_BYTES:
            return None
        value = json.loads(path.read_bytes().decode('utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, ValueError, RecursionError):
        return None


def _tenant_dir(tenants_dir: Path, tenant: str) -> Path | None:
    if not isinstance(tenant, str) or not tenant or tenant in ('.', '..') or '/' in tenant or '\\' in tenant or '\0' in tenant:
        return None
    try:
        path = Path(tenants_dir) / tenant
        if path.is_symlink() or not path.is_dir():
            return None
        return path
    except OSError:
        return None


def _read_bytes(path: Path) -> bytes | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _read_yaml(path: Path):
    raw = _read_bytes(path)
    if raw is None:
        return None
    try:
        return yaml.safe_load(raw.decode('utf-8'))
    except (OSError, ValueError, UnicodeError, yaml.YAMLError, RecursionError):
        return None


def _read_text(path: Path) -> str | None:
    raw = _read_bytes(path)
    if raw is None:
        return None
    try:
        return raw.decode('utf-8')
    except UnicodeError:
        return None


def load_proposals(tenant_dir: Path) -> dict[str, str]:
    """Latest valid proposal per ask id from the bounded newest tail of the journal."""
    path = tenant_dir / 'asks' / 'proposed.jsonl'
    proposals: dict[str, str] = {}
    try:
        if path.is_symlink() or not path.is_file():
            return proposals
        size = path.stat().st_size
        with path.open('rb') as stream:
            if size > MAX_FILE_BYTES:
                stream.seek(size - MAX_FILE_BYTES)
            raw = stream.read(MAX_FILE_BYTES)
        text = raw.decode('utf-8', errors='replace')
        if size > MAX_FILE_BYTES:
            # Drop the partial first line of an append-only journal's tail.
            text = text.split('\n', 1)[1] if '\n' in text else ''
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            proposed, ask = record.get('proposed'), record.get('ask_id')
            if not isinstance(ask, str) or not isinstance(proposed, str):
                continue
            if (not proposed.strip() or len(proposed) > MAX_PROPOSED or SENSITIVE_RE.search(proposed)
                    or CONTROL_RE.search(proposed)):
                continue
            proposals[ask] = proposed
    except (OSError, UnicodeError):
        pass
    return proposals


def _fact_asks(tenant_dir: Path, tenant: str, proposals: dict[str, str]) -> list[dict]:
    context = tenant_dir / 'context'
    asks: list[dict] = []
    if context.is_symlink() or not context.is_dir():
        return asks
    for path in sorted(context.glob('*.md')):
        if path.name == 'open-questions.md':
            continue
        text = _read_text(path)
        if text is None:
            continue
        source = f"context/{path.name}"
        for line in text.splitlines():
            match = FILL_RE.match(line)
            if not match:
                continue
            value = match.group(1).strip()
            if not value or SENSITIVE_RE.search(value):
                continue
            key = f"{source}|{value}"
            proposed = proposals.get(ask_id(tenant, 'fact', key))
            asks.append({'id': ask_id(tenant, 'fact', key), 'tenant': tenant, 'kind': 'fact',
                         'role': ROLE_FOR_KIND['fact'], 'title': value[:MAX_TITLE], 'source': source,
                         'answer_type': 'yes_no' if proposed is not None else 'text', 'proposed': proposed})
    return asks


def _decision_asks(tenant: str, proposal: dict | None) -> list[dict]:
    asks: list[dict] = []
    if not isinstance(proposal, dict):
        return asks
    flows = proposal.get('cross_brand_flows')
    if not isinstance(flows, list):
        return asks
    for flow in flows:
        if not isinstance(flow, dict) or flow.get('status') == 'approved':
            continue
        participants = flow.get('participants')
        if not isinstance(participants, list) or tenant not in participants:
            continue
        flow_id = flow.get('id')
        if not isinstance(flow_id, str) or not ID_RE.fullmatch(flow_id):
            continue
        description = flow.get('description')
        title = description if isinstance(description, str) and description.strip() else f"Flow {flow_id}"
        title = title.strip()
        if SENSITIVE_RE.search(title):
            continue
        key = f"flow|{flow_id}"
        asks.append({'id': ask_id(tenant, 'decision', key), 'tenant': tenant, 'kind': 'decision',
                     'role': ROLE_FOR_KIND['decision'], 'title': title[:MAX_TITLE],
                     'source': 'portfolio-map-proposal.json', 'answer_type': 'yes_no', 'proposed': None})
    return asks


def _not_admitted(source: dict) -> bool:
    if 'admitted' in source:
        return source.get('admitted') is not True
    # Real sources.yaml files use `ingest`, not `admitted`.
    return source.get('ingest') is not True


def _source_connect_asks(tenant: str, sources_value) -> list[dict]:
    asks: list[dict] = []
    if not isinstance(sources_value, dict):
        return asks
    sources = sources_value.get('sources')
    if not isinstance(sources, list):
        return asks
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get('id')
        if not isinstance(source_id, str) or not ID_RE.fullmatch(source_id) or not _not_admitted(source):
            continue
        key = f"source|{source_id}"
        asks.append({'id': ask_id(tenant, 'connect', key), 'tenant': tenant, 'kind': 'connect',
                     'role': ROLE_FOR_KIND['connect'], 'title': f"Connect {source_id}",
                     'source': 'sources.yaml', 'answer_type': 'yes_no', 'proposed': None})
    return asks


def _module_connect_asks(tenant: str, enabled_value) -> list[dict]:
    asks: list[dict] = []
    if not isinstance(enabled_value, dict):
        return asks
    modules = enabled_value.get('modules')
    if not isinstance(modules, list):
        return asks
    for module in modules:
        if not isinstance(module, dict) or module.get('category') not in ('mcp', 'connector'):
            continue
        module_id = module.get('id')
        if not isinstance(module_id, str) or not ID_RE.fullmatch(module_id):
            continue
        key = f"module|{module_id}"
        asks.append({'id': ask_id(tenant, 'connect', key), 'tenant': tenant, 'kind': 'connect',
                     'role': ROLE_FOR_KIND['connect'], 'title': f"Connect {module_id}",
                     'source': 'enabled.yaml', 'answer_type': 'yes_no', 'proposed': None})
    return asks


def _website_ask(tenant: str, manifest) -> list[dict]:
    if not isinstance(manifest, dict):
        return []
    brand = manifest.get('brand')
    if not isinstance(brand, dict):
        return []
    domain = brand.get('domain')
    if not isinstance(domain, str):
        return []
    match = re.match(r'FILL:\s*(.*)$', domain.strip())
    if not match:
        return []
    title = match.group(1).strip()
    if not title:
        title = 'Confirm brand domain'
    if SENSITIVE_RE.search(title):
        return []
    title = title[:MAX_TITLE]
    key = 'domain'
    return [{'id': ask_id(tenant, 'website', key), 'tenant': tenant, 'kind': 'website',
             'role': ROLE_FOR_KIND['website'], 'title': title, 'source': 'MANIFEST.yaml',
             'answer_type': 'text', 'proposed': None}]


def _brand_ask(tenant: str, sources_value) -> list[dict]:
    if not isinstance(sources_value, dict):
        return []
    sources = sources_value.get('sources')
    if not isinstance(sources, list):
        return []
    for source in sources:
        if isinstance(source, dict) and isinstance(source.get('id'), str) and 'meristem' in source['id'].lower():
            return []
    title = 'Meristem brand handoff'
    if SENSITIVE_RE.search(title):
        return []
    key = 'meristem'
    return [{'id': ask_id(tenant, 'brand', key), 'tenant': tenant, 'kind': 'brand',
             'role': ROLE_FOR_KIND['brand'], 'title': title, 'source': 'sources.yaml',
             'answer_type': 'yes_no', 'proposed': None}]


def _clean_text(value):
    return ' '.join(CONTROL_RE.sub(' ', value).split()) if isinstance(value, str) else ''


def derive_asks(tenants_dir: Path, tenant: str, proposal: dict | None = None) -> list[dict]:
    tenant_dir = _tenant_dir(tenants_dir, tenant)
    if tenant_dir is None:
        return []
    proposals = load_proposals(tenant_dir)
    sources_value = _read_yaml(tenant_dir / 'sources.yaml')
    enabled_value = _read_yaml(tenant_dir / 'enabled.yaml')
    manifest = _read_yaml(tenant_dir / 'MANIFEST.yaml')
    asks: list[dict] = []
    asks += _fact_asks(tenant_dir, tenant, proposals)
    asks += _decision_asks(tenant, proposal)
    asks += _source_connect_asks(tenant, sources_value)
    asks += _module_connect_asks(tenant, enabled_value)
    asks += _website_ask(tenant, manifest)
    asks += _brand_ask(tenant, sources_value)
    # A repeated FILL line, flow, source or module would repeat a stable id;
    # clients reject duplicate ids, so keep the first occurrence only.
    seen, unique = set(), []
    for ask in asks:
        # Ids come from keys, so normalizing display text never moves an answer.
        ask['title'] = _clean_text(ask['title'])[:MAX_TITLE]
        ask['source'] = _clean_text(ask['source'])[:MAX_SOURCE]
        # Re-check the final text: normalization can join a split sensitive word,
        # and connect titles are built from raw source and module ids.
        if (not ask['title'] or not ask['source'] or ask['id'] in seen
                or SENSITIVE_RE.search(ask['title']) or SENSITIVE_RE.search(ask['source'])):
            continue
        seen.add(ask['id'])
        unique.append(ask)
    return unique[:MAX_ASKS]
