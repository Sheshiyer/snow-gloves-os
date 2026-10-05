"""Minimal PII redactor for audit logs."""
import re
EMAIL = re.compile(r"[\w\.\-+]+@[\w\.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+?\d[\d\s\-().]{7,}\d)")
CARD  = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
TOKEN = re.compile(r"(?i)(?:bearer|token|secret|api[_-]?key)[\"':=\s]+([\w\-\.]{16,})")
SHA256 = re.compile(r"[0-9a-fA-F]{64}")
DIGEST_FIELDS = frozenset({"sha256", "source_sha256", "artifact_sha256"})

def redact_text(s: str) -> str:
    s = EMAIL.sub("[email]", s)
    s = CARD.sub("[card]", s)
    s = PHONE.sub("[phone]", s)
    s = TOKEN.sub(lambda m: m.group(0).replace(m.group(1), "[secret]"), s)
    return s

def redact(obj):
    if isinstance(obj, str): return redact_text(obj)
    if isinstance(obj, list): return [redact(x) for x in obj]
    if isinstance(obj, dict):
        # Typed content digests are evidence, not phone numbers. Only exact
        # SHA-256 values in these named fields bypass free-text redaction.
        return {k: v if (k in DIGEST_FIELDS and isinstance(v, str)
                         and SHA256.fullmatch(v)) else redact(v)
                for k, v in obj.items()}
    return obj
