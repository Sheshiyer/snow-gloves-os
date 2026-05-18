"""Minimal PII redactor for audit logs."""
import re
EMAIL = re.compile(r"[\w\.\-+]+@[\w\.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+?\d[\d\s\-().]{7,}\d)")
CARD  = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
TOKEN = re.compile(r"(?i)(?:bearer|token|secret|api[_-]?key)[\"':=\s]+([\w\-\.]{16,})")

def redact_text(s: str) -> str:
    s = EMAIL.sub("[email]", s)
    s = CARD.sub("[card]", s)
    s = PHONE.sub("[phone]", s)
    s = TOKEN.sub(lambda m: m.group(0).replace(m.group(1), "[secret]"), s)
    return s

def redact(obj):
    if isinstance(obj, str): return redact_text(obj)
    if isinstance(obj, list): return [redact(x) for x in obj]
    if isinstance(obj, dict): return {k: redact(v) for k, v in obj.items()}
    return obj
