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
import os
import re
import time
from pathlib import Path

from .cockpit_tenant_map import (card_gate, open_nofollow, read_catalog, read_enablement, read_manifest, read_raw,
                                 read_sources, read_templates)

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
MAX_CONTEXT_ENTRIES = 1024  # directory entries considered in context/
MAX_CONTEXT_BYTES = 8 * 1024 * 1024  # all context files read for one derivation
MAX_CONTEXT_SECONDS = 2
# Clients reject strings containing C0 control characters (or DEL); every
# emitted string is checked or normalized against this one pattern.
CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')
MAX_PROPOSED = 500
MAX_FILE_BYTES = 256 * 1024
MAX_PROPOSAL_LINE = 64 * 1024  # one journal record; the importer writes far less
MAX_PROPOSAL_SCAN_BYTES = 32 * 1024 * 1024  # total read per listing
MAX_PROPOSAL_IDS = MAX_ASKS * 4  # distinct ask ids kept from the journal, with headroom over MAX_ASKS
PROPOSAL_MAX_BYTES = 512 * 1024
PROPOSAL_REL = Path('specs') / '006-editorial-steward-integration' / 'portfolio-map-proposal.json'

FILL_RE = re.compile(r'^\s*-?\s*FILL:\s*(.+)$')
ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')
SENSITIVE_RE = re.compile(r"(?i)(?:^|[^a-z0-9])(?:secret|password|passwd|credentials?|token|bearer)(?:$|[^a-z0-9])|api[_. -]?key|(?:^|[^a-z0-9])(?:sk-|ghp_|github_pat_)")


def ask_id(tenant: str, kind: str, key: str) -> str:
    return hashlib.sha256(f"{tenant}|{kind}|{key}".encode('utf-8')).hexdigest()[:32]


def is_scalar_text(value) -> bool:
    """True when *value* is a str of Unicode scalar values (no lone surrogates)."""
    if not isinstance(value, str):
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def load_proposal(data_root: Path) -> dict | None:
    # Every component, the file and its parent directories included, is opened without
    # following links, so a link placed before or after any check is never read through.
    raw, _ = read_raw(Path(data_root) / PROPOSAL_REL, PROPOSAL_MAX_BYTES)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode('utf-8'))
        return value if isinstance(value, dict) else None
    except (UnicodeError, ValueError, RecursionError):
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
    # Every component is opened without following links, so a file or directory
    # swapped for a link after any check cannot pull in another tenant's text.
    return read_raw(path, MAX_FILE_BYTES)[0]


def _read_text(path: Path) -> str | None:
    raw = _read_bytes(path)
    if raw is None:
        return None
    try:
        return raw.decode('utf-8')
    except UnicodeError:
        return None


def load_proposals(tenant_dir: Path, wanted: set[str] | None = None) -> dict[str, str]:
    """Latest valid proposal per ask id, streamed over the whole journal.

    The importer appends a proposal only once per value, so an ask's only record
    can sit anywhere in the file. With *wanted* (the tenant's current ask ids)
    only those ids are kept, so history never crowds out a current ask. Without
    it, at most MAX_PROPOSAL_IDS ids are kept, evicting the least recently
    written, so a new ask always gets its proposal. Lines over the line cap are skipped.
    """
    asks_dir = tenant_dir / 'asks'
    path = asks_dir / 'proposed.jsonl'
    proposals: dict[str, str] = {}
    try:
        # Never follow a link at the asks directory or the journal itself, and
        # require the resolved journal to stay inside this tenant.
        if (asks_dir.is_symlink() or path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(tenant_dir.resolve())):
            return proposals
        with os.fdopen(open_nofollow(path), 'rb') as stream:
            scanned = 0
            while True:
                raw = stream.readline(MAX_PROPOSAL_LINE + 1)
                scanned += len(raw)
                # The importer compacts the journal past a few MiB, so this hard budget only
                # stops a journal it never got to compact from stalling every ask listing.
                if not raw or scanned > MAX_PROPOSAL_SCAN_BYTES:
                    break
                if len(raw) > MAX_PROPOSAL_LINE:
                    # Skip the rest of an oversized line without holding it, inside the same budget.
                    while raw and not raw.endswith(b'\n') and scanned <= MAX_PROPOSAL_SCAN_BYTES:
                        raw = stream.readline(MAX_PROPOSAL_LINE)
                        scanned += len(raw)
                    continue
                try:
                    record = json.loads(raw.decode('utf-8', errors='replace'))
                except (ValueError, TypeError, RecursionError):  # deep nesting: skip the line
                    continue
                if not isinstance(record, dict):
                    continue
                proposed, ask = record.get('proposed'), record.get('ask_id')
                if not isinstance(ask, str) or not isinstance(proposed, str):
                    continue
                if (not proposed.strip() or len(proposed) > MAX_PROPOSED or SENSITIVE_RE.search(proposed)
                        or CONTROL_RE.search(proposed) or not is_scalar_text(proposed)):
                    continue
                if wanted is not None:
                    if ask in wanted:
                        proposals[ask] = proposed
                    continue
                proposals.pop(ask, None)
                proposals[ask] = proposed
                if len(proposals) > MAX_PROPOSAL_IDS:
                    del proposals[next(iter(proposals))]
    except (OSError, UnicodeError):
        pass
    return proposals


def _fact_asks(tenant_dir: Path, tenant: str, proposals: dict[str, str]) -> list[dict]:
    context = tenant_dir / 'context'
    asks: list[dict] = []
    if context.is_symlink() or not context.is_dir():
        return asks
    # Bound the traversal and stop once the ask budget is spent.
    names = []
    try:
        with os.scandir(context) as entries:
            for count, entry in enumerate(entries):
                if count >= MAX_CONTEXT_ENTRIES:
                    break
                if entry.name.endswith('.md') and entry.name != 'open-questions.md':
                    names.append(entry.name)
    except OSError:
        return asks
    seen: set[str] = set()
    # One budget for the whole scan: listings repeat it and answers run it under the
    # coordinator lock, so many large files must not add up to a long stall.
    read, deadline = 0, time.monotonic() + MAX_CONTEXT_SECONDS
    for name in sorted(names):
        if len(asks) >= MAX_ASKS or read >= MAX_CONTEXT_BYTES or time.monotonic() > deadline:
            break
        path = context / name
        raw = _read_bytes(path)
        if raw is None:
            continue
        # Count the bytes read, not decoded characters, and count undecodable files too.
        read += len(raw)
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            continue
        source = f"context/{path.name}"
        # The checks keep() applies to the final text run here too, before an ask is counted:
        # lines that only normalize into something refused must not spend the budget.
        shown_source = _clean_text(source)[:MAX_SOURCE]
        if not shown_source or SENSITIVE_RE.search(shown_source) or not is_scalar_text(shown_source):
            continue
        for line in text.splitlines():
            match = FILL_RE.match(line)
            if not match:
                continue
            value = match.group(1).strip()
            if not value or SENSITIVE_RE.search(value):
                continue
            shown = _clean_text(value)[:MAX_TITLE]
            if not shown or SENSITIVE_RE.search(shown) or not is_scalar_text(shown):
                continue
            key = f"{source}|{value}"
            identity = ask_id(tenant, 'fact', key)
            # A repeated FILL line is one ask; never let copies spend the budget.
            if identity in seen:
                continue
            seen.add(identity)
            proposed = proposals.get(identity)
            asks.append({'id': identity, 'tenant': tenant, 'kind': 'fact',
                         'role': ROLE_FOR_KIND['fact'], 'title': value[:MAX_TITLE], 'source': source,
                         'answer_type': 'yes_no' if proposed is not None else 'text', 'proposed': proposed})
            if len(asks) >= MAX_ASKS:
                break
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
        # The ask is bound to the decision text it shows: a revised description is a new
        # question, so an earlier yes/no (or a stale click on the old text) cannot answer it.
        digest = hashlib.sha256(title.encode('utf-8', 'surrogatepass')).hexdigest()[:16]
        key = f"flow|{flow_id}|{digest}"
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


def load_catalog(code_root: Path) -> dict[str, str]:
    """Module id -> category for catalog cards the tenant view permits; every held card is left out.

    The catalog is read through the capability view's reader, so a catalog the
    tenant view holds (too large, wrong schema, malformed) yields no connector asks.
    """
    _, cards, controls, state = read_catalog(Path(code_root))
    if state != 'configured':
        return {}
    templates, _ = read_templates(Path(code_root))
    known_roles = {role['id'] for role in controls + templates}
    # The tenant view's own gate: a card it shows as held never becomes an ask.
    return {ident: card['category'] for ident, card in cards.items() if card_gate(card, known_roles)[4]}


def _module_connect_asks(tenant: str, enabled_value, catalog: dict[str, str] | None = None) -> list[dict]:
    asks: list[dict] = []
    if not isinstance(enabled_value, dict):
        return asks
    modules = enabled_value.get('modules')
    if not isinstance(modules, list):
        return asks
    for module in modules:
        # Entries may be bare ids; the catalog, when given, decides the category.
        module_id = module.get('id') if isinstance(module, dict) else module
        if not isinstance(module_id, str) or not ID_RE.fullmatch(module_id):
            continue
        if catalog is not None:
            category = catalog.get(module_id)
        else:
            category = module.get('category') if isinstance(module, dict) else None
        if category not in ('mcp', 'connector'):
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
    # Bound to the prompt it shows, as fact and decision asks are: a revised FILL prompt is a
    # new question, so an earlier answer (or a form opened before the edit) cannot answer it.
    key = 'domain|' + hashlib.sha256(title.encode('utf-8', 'surrogatepass')).hexdigest()[:16]
    title = title[:MAX_TITLE]
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


def derive_asks(tenants_dir: Path, tenant: str, proposal: dict | None = None,
                catalog: dict[str, str] | None = None) -> list[dict]:
    tenant_dir = _tenant_dir(tenants_dir, tenant)
    if tenant_dir is None:
        return []
    # Load proposals only for the fact asks that exist now, so journal history
    # can never crowd a current ask out of its proposal.
    fact_asks = _fact_asks(tenant_dir, tenant, {})
    proposals = load_proposals(tenant_dir, {ask['id'] for ask in fact_asks})
    for ask in fact_asks:
        if ask['id'] in proposals:
            ask.update(answer_type='yes_no', proposed=proposals[ask['id']])
    # Source and brand asks come only from a sources.yaml the tenant view accepts.
    sources_value, _ = read_sources(tenant_dir)
    # Share the capability view's fail-closed parser: held enablement asks for no connector.
    enabled_value, _ = read_enablement(tenant_dir)
    manifest, _ = read_manifest(tenant_dir)
    # Decision, connect, website and brand asks are few and actionable; derive
    # them first so a long run of FILL lines can only spend the remaining budget.
    # Within them, connection, website and brand asks are bounded (source and module
    # rows are capped by the tenant view's readers) and come before decisions, so a
    # long portfolio proposal can only spend what they leave.
    others: list[dict] = []
    others += _source_connect_asks(tenant, sources_value)
    others += _module_connect_asks(tenant, enabled_value, catalog)
    others += _website_ask(tenant, manifest)
    others += _brand_ask(tenant, sources_value)
    others += _decision_asks(tenant, proposal)
    seen: set[str] = set()

    def keep(asks: list[dict]) -> list[dict]:
        # A repeated FILL line, flow, source or module would repeat a stable id;
        # clients reject duplicate ids, so keep the first occurrence only.
        unique = []
        for ask in asks:
            # Ids come from keys, so normalizing display text never moves an answer.
            ask['title'] = _clean_text(ask['title'])[:MAX_TITLE]
            ask['source'] = _clean_text(ask['source'])[:MAX_SOURCE]
            # Re-check the final text: normalization can join a split sensitive word,
            # and connect titles are built from raw source and module ids.
            if (not ask['title'] or not ask['source'] or ask['id'] in seen
                    or SENSITIVE_RE.search(ask['title']) or SENSITIVE_RE.search(ask['source'])
                    or not is_scalar_text(ask['title']) or not is_scalar_text(ask['source'])):
                continue
            seen.add(ask['id'])
            unique.append(ask)
        return unique

    # Budget by priority, then show decisions first as before.
    others = sorted(keep(others)[:MAX_ASKS], key=lambda ask: ask['kind'] != 'decision')
    facts = keep(fact_asks)[:MAX_ASKS - len(others)]
    # Decisions first, then connection, website and brand asks, then facts.
    return others + facts
