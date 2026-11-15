"""Secret-like string detection. Callers only ever get pattern names and counts, never the matched values."""
from __future__ import annotations

import base64
import math
import re

SECRET_PATTERNS: dict[str, re.Pattern] = {
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "stripe_live_key": re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "credential_assignment": re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"']([A-Za-z0-9/+_\-!@#$%^&*]{12,})[\"']"),
    "connection_string_with_password": re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:([^\s@/]{6,})@"),
}
GENERIC_PATTERNS = {"credential_assignment", "connection_string_with_password"}
PLACEHOLDER_RE = re.compile(
    r"(?i)x{4,}|\*{3,}|\.{3}|<[^>]+>|\$\{?[A-Z_]+|your|example|placeholder|changeme|dummy|test|fake|sample|redacted|"
    r"secret_here|0{8,}|1234|abcd|password123|\{\{")
LOCAL_HOST_RE = re.compile(r"@(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal|db|postgres|mysql|redis|mongo|database)\b", re.I)
DEV_PASSWORD_RE = re.compile(r"(?i)^(?:password|passwd|postgres|secret|dev|devpass|test|guest|admin|root|pass|changeme|example)\w{0,4}$")
KEY_MATERIAL_RE = re.compile(r"[A-Za-z0-9+/]{40,}")
EXAMPLE_JWT_PAYLOAD_RE = re.compile(r"(?i)john doe|1234567890|example|test|demo|\"sub\":\s*\"(?:user|123)")
MIN_GENERIC_LENGTH = 16
MIN_GENERIC_ENTROPY = 3.5


def entropy(s: str) -> float:
    """Shannon entropy in bits per character."""
    if not s:
        return 0.0
    return -sum(s.count(c) / len(s) * math.log2(s.count(c) / len(s)) for c in set(s))


def scan_raw(text: str) -> dict[str, int]:
    """What a plain regex scanner would report, for comparison with `scan`."""
    return {name: n for name, rx in SECRET_PATTERNS.items() if (n := len(rx.findall(text)))}


def scan(text: str) -> dict[str, int]:
    hits: dict[str, int] = {}
    for name, rx in SECRET_PATTERNS.items():
        for m in rx.finditer(text):
            if _looks_real(name, m, text):
                hits[name] = hits.get(name, 0) + 1
    return hits


def _looks_real(name: str, m: re.Match, text: str) -> bool:
    value = m.group(m.lastindex) if m.lastindex else m.group(0)
    if PLACEHOLDER_RE.search(value):
        return False
    if name in GENERIC_PATTERNS:
        context = text[max(0, m.start() - 20):m.end() + 20]
        if PLACEHOLDER_RE.search(context) or DEV_PASSWORD_RE.match(value):
            return False
        if name == "connection_string_with_password" and LOCAL_HOST_RE.search(text[m.start():m.end() + 40]):
            return False
        if len(value) < MIN_GENERIC_LENGTH or entropy(value) < MIN_GENERIC_ENTROPY:
            return False
    if name == "private_key_block" and not KEY_MATERIAL_RE.search(text[m.end():m.end() + 300]):
        return False
    return not (name == "jwt" and _is_example_jwt(value))


def _is_example_jwt(token: str) -> bool:
    try:
        part = token.split(".")[1]
        payload = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8", "replace")
    except (IndexError, ValueError):
        return False
    return bool(EXAMPLE_JWT_PAYLOAD_RE.search(payload))
