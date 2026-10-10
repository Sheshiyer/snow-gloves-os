"""Strict bounded evidence contract for manual, read-only CTO write reviews."""
import hashlib
import json
import re
from pathlib import PurePosixPath


SCHEMA = 'snowgloves.write-review.v1'
MAX_ARTIFACT_BYTES = 1_000_000
MAX_PATCH_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 96 * 1024
MAX_FILES = 100
MAX_TESTS = 16
MAX_TEST_SUMMARY = 2000
HEX64 = re.compile(r'^[a-f0-9]{64}$')
HEX_OBJECT = re.compile(r'^(?:[a-f0-9]{40}|[a-f0-9]{64})$')
TASK_ID = re.compile(r'^[a-f0-9]{32}$')
SECRET_LIKE = re.compile(
    r'(?i)(?:\bBearer\s+\S+|\b(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,})'
    r'|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+)'
)
DIFF_HEADER = re.compile(r'^diff --git a/([^\s]+) b/([^\s]+)$', re.MULTILINE)


class ReviewEvidenceError(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ReviewEvidenceError('duplicate JSON key')
        result[key] = value
    return result


def _constant(_value):
    raise ReviewEvidenceError('non-finite JSON value')


def _json_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ReviewEvidenceError('invalid review evidence JSON') from None


def _safe_path(value):
    if (type(value) is not str or not value or len(value) > 512 or '\x00' in value
            or '\\' in value or any(ord(char) < 0x20 for char in value)):
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in ('', '.', '..') for part in value.split('/')):
        return False
    if any(part in ('.git', '.github', '_runtime') or part.lower().startswith('.env') for part in path.parts):
        return False
    if re.search(r'(?i)(?:^|/)(?:id_(?:rsa|ed25519)[^/]*|credentials[^/]*|[^/]+\.(?:pem|key|p12|pfx|token|secret))$', value):
        return False
    return True


def _validate_files(files):
    if type(files) is not list or not 1 <= len(files) <= MAX_FILES:
        raise ReviewEvidenceError('invalid reviewed file list')
    if any(not _safe_path(path) for path in files):
        raise ReviewEvidenceError('unsafe reviewed file path')
    if files != sorted(files) or len(set(files)) != len(files):
        raise ReviewEvidenceError('reviewed files must be sorted and unique')
    return files


def _secret_check(text, secrets):
    if SECRET_LIKE.search(text):
        raise ReviewEvidenceError('patch contains credential-like content')
    for secret in secrets:
        if type(secret) is str and secret and secret in text:
            raise ReviewEvidenceError('patch contains a coordinator credential')


def _validate_diff_metadata(text, matches):
    """Bind Git's actual file headers to the declared paths, before hunk data."""
    for index, match in enumerate(matches):
        old, new = match.groups()
        if old != new:
            raise ReviewEvidenceError('rename or copy patches are not supported')
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        headers = {}
        for line in text[match.end():end].splitlines():
            if line.startswith('@@ '):
                break  # ---/+++ within a hunk are file contents, not metadata.
            if not line:
                continue
            if line.startswith(('--- ', '+++ ')):
                prefix = line[:4]
                if prefix in headers:
                    raise ReviewEvidenceError('duplicate patch file header')
                path = line[4:]
                expected = ('a/' + old) if prefix == '--- ' else ('b/' + new)
                if path not in (expected, '/dev/null'):
                    raise ReviewEvidenceError('patch file headers do not match declared paths')
                headers[prefix] = path
            elif line.startswith(('old mode ', 'new mode ', 'new file mode ', 'deleted file mode ')):
                if line.rsplit(' ', 1)[-1] not in ('100644', '100755'):
                    raise ReviewEvidenceError('patch has an unsupported file mode')
            elif line.startswith('index '):
                if not re.fullmatch(r'index [a-f0-9]+\.\.[a-f0-9]+(?: (?:100644|100755))?', line):
                    raise ReviewEvidenceError('patch has unsupported index metadata')
            else:
                raise ReviewEvidenceError('patch has unsupported file metadata')
        if headers and (set(headers) != {'--- ', '+++ '}
                        or all(path == '/dev/null' for path in headers.values())):
            raise ReviewEvidenceError('patch has incomplete file headers')


def validate_evidence(value, secrets=()):
    """Validate the closed worker-delivery schema and return a detached value."""
    fields = {'schema', 'task_id', 'attempt_id', 'artifact_sha256', 'base', 'files', 'patch', 'tests'}
    if type(value) is not dict or set(value) != fields or value.get('schema') != SCHEMA:
        raise ReviewEvidenceError('invalid review evidence schema')
    if type(value['task_id']) is not str or not TASK_ID.fullmatch(value['task_id']):
        raise ReviewEvidenceError('invalid review task id')
    if type(value['attempt_id']) is not str or not TASK_ID.fullmatch(value['attempt_id']):
        raise ReviewEvidenceError('invalid review attempt id')
    if type(value['artifact_sha256']) is not str or not HEX64.fullmatch(value['artifact_sha256']):
        raise ReviewEvidenceError('invalid source artifact digest')
    if type(value['base']) is not str or not HEX_OBJECT.fullmatch(value['base']):
        raise ReviewEvidenceError('invalid patch base')
    files = _validate_files(value['files'])
    patch = value['patch']
    if type(patch) is not dict or set(patch) != {'text', 'sha256', 'bytes'}:
        raise ReviewEvidenceError('invalid patch object')
    if type(patch['text']) is not str:
        raise ReviewEvidenceError('patch must be text')
    try:
        patch_bytes = patch['text'].encode('utf-8', 'strict')
    except UnicodeError:
        raise ReviewEvidenceError('patch is not valid UTF-8') from None
    if not patch_bytes or len(patch_bytes) > MAX_PATCH_BYTES or b'\x00' in patch_bytes:
        raise ReviewEvidenceError('patch is empty or exceeds the review bound')
    if 'GIT binary patch' in patch['text'] or any(line.startswith('Binary files ') for line in patch['text'].splitlines()):
        raise ReviewEvidenceError('binary patches are not reviewable')
    if type(patch['bytes']) is not int or patch['bytes'] != len(patch_bytes):
        raise ReviewEvidenceError('patch byte count is invalid')
    if type(patch['sha256']) is not str or not HEX64.fullmatch(patch['sha256']) or hashlib.sha256(patch_bytes).hexdigest() != patch['sha256']:
        raise ReviewEvidenceError('patch digest is invalid')
    _secret_check(patch['text'], secrets)
    diff_files = []
    diff_lines = [line for line in patch['text'].splitlines() if line.startswith('diff --git ')]
    matches = list(DIFF_HEADER.finditer(patch['text']))
    if len(matches) != len(diff_lines):
        raise ReviewEvidenceError('patch has an unsupported diff header')
    _validate_diff_metadata(patch['text'], matches)
    for match in matches:
        old, new = match.groups()
        old_path, new_path = old, new
        if not _safe_path(old_path) or not _safe_path(new_path):
            raise ReviewEvidenceError('patch contains an unsafe diff path')
        diff_files.extend((old_path, new_path))
    normalized_diff = sorted(set(diff_files))
    if not normalized_diff or normalized_diff != files:
        raise ReviewEvidenceError('patch paths do not match reviewed file list')
    tests = value['tests']
    if type(tests) is not list or not 1 <= len(tests) <= MAX_TESTS:
        raise ReviewEvidenceError('invalid review test results')
    clean_tests = []
    for test in tests:
        if type(test) is not dict or set(test) != {'status', 'exit_code', 'summary', 'output_sha256'}:
            raise ReviewEvidenceError('invalid review test result')
        if (test['status'] != 'passed' or type(test['exit_code']) is not int or test['exit_code'] != 0
                or type(test['summary']) is not str or not test['summary'].strip()
                or len(test['summary']) > MAX_TEST_SUMMARY or '\x00' in test['summary']
                or type(test['output_sha256']) is not str or not HEX64.fullmatch(test['output_sha256'])):
            raise ReviewEvidenceError('review tests must have bounded successful summaries')
        clean_tests.append(dict(test))
    result = {
        'schema': SCHEMA, 'task_id': value['task_id'], 'attempt_id': value['attempt_id'],
        'artifact_sha256': value['artifact_sha256'], 'base': value['base'],
        'files': list(files), 'patch': dict(patch), 'tests': clean_tests,
    }
    if len(_json_bytes(result)) > MAX_EVIDENCE_BYTES:
        raise ReviewEvidenceError('review evidence exceeds delivery bound')
    _secret_check(patch['text'], secrets)
    return result


def evidence_from_artifact(raw, task_id, attempt_id, artifact_sha256, secrets=()):
    """Convert one checksum-verified write artifact into bounded review evidence."""
    if type(raw) is not bytes or len(raw) > MAX_ARTIFACT_BYTES:
        raise ReviewEvidenceError('source artifact exceeds review bound')
    if (type(artifact_sha256) is not str or not HEX64.fullmatch(artifact_sha256)
            or hashlib.sha256(raw).hexdigest() != artifact_sha256):
        raise ReviewEvidenceError('source artifact checksum is invalid')
    try:
        envelope = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_pairs,
                              parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ReviewEvidenceError('source artifact is invalid JSON') from None
    expected = {'task_id', 'attempt_id', 'node', 'runtime', 'model', 'output', 'access',
                'base', 'files', 'patch', 'tests'}
    if type(envelope) is not dict or set(envelope) != expected:
        raise ReviewEvidenceError('source artifact schema is invalid')
    if (envelope['task_id'] != task_id or envelope['attempt_id'] != attempt_id
            or envelope['runtime'] != 'codex' or envelope['access'] != 'write'):
        raise ReviewEvidenceError('source artifact binding is invalid')
    for field, limit in (('node', 100), ('model', 200), ('output', 16000)):
        if type(envelope[field]) is not str or len(envelope[field]) > limit or '\x00' in envelope[field]:
            raise ReviewEvidenceError('source artifact metadata is invalid')
        try:
            if len(envelope[field].encode('utf-8', 'strict')) > limit * 4:
                raise ReviewEvidenceError('source artifact metadata is invalid')
        except UnicodeError:
            raise ReviewEvidenceError('source artifact metadata is invalid') from None
    files = _validate_files(envelope['files'])
    patch = envelope['patch']
    if type(patch) is not dict or set(patch) != {'text', 'sha256', 'bytes'}:
        raise ReviewEvidenceError('source patch schema is invalid')
    tests = envelope['tests']
    if type(tests) is not list or not 1 <= len(tests) <= MAX_TESTS:
        raise ReviewEvidenceError('source tests are invalid')
    clean_tests = []
    for test in tests:
        if type(test) is not dict or set(test) != {'argv', 'exit_code', 'tail'}:
            raise ReviewEvidenceError('source test schema is invalid')
        argv, exit_code, tail = test['argv'], test['exit_code'], test['tail']
        if (type(argv) is not list or not argv or len(argv) > 64
                or any(type(arg) is not str or len(arg) > 512 or '\x00' in arg for arg in argv)
                or type(exit_code) is not int or exit_code != 0 or type(tail) is not str
                or len(tail) > MAX_TEST_SUMMARY or '\x00' in tail):
            raise ReviewEvidenceError('source tests must be bounded and successful')
        try:
            tail_bytes = tail.encode('utf-8', 'strict')
        except UnicodeError:
            raise ReviewEvidenceError('source test summary is invalid') from None
        clean_tests.append({'status': 'passed', 'exit_code': 0, 'summary': 'Test command passed',
                            'output_sha256': hashlib.sha256(tail_bytes).hexdigest()})
    evidence = {
        'schema': SCHEMA, 'task_id': task_id, 'attempt_id': attempt_id,
        'artifact_sha256': artifact_sha256, 'base': envelope['base'], 'files': files,
        'patch': patch, 'tests': clean_tests,
    }
    return validate_evidence(evidence, secrets)
