"""Secret redaction (PDF §7 "no secret exfiltration", §10 audit).

Applied to logs, events, explanations, PR bodies, and anything rendered for
review. Detection is pattern-based and intentionally broad; when in doubt it
masks. Secrets must NEVER be sent to the LLM — callers scrub context first.
"""
from __future__ import annotations

import re
from typing import Any

MASK = "***REDACTED***"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub tokens
    (re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}"), MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), MASK),
    # Cloud / provider keys
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), MASK),
    (re.compile(r"\bsk-(live|test)-[A-Za-z0-9]{10,}"), MASK),
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[^-]*-----END [A-Z0-9 ]*PRIVATE KEY-----"), MASK),
    # Authorization headers
    (re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9\-._~+/]{12,}={0,2}"), r"\1 " + MASK),
    (re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/]{12,}={0,2}"), r"\1 " + MASK),
    # key=value style secrets (keep the key name, mask the value)
    (
        re.compile(
            r"(?i)\b(api[_-]?key|api[_-]?secret|secret|token|password|passwd|pwd|"
            r"client[_-]?secret|access[_-]?key|private[_-]?key)\b(\s*[:=]\s*)(['\"]?)([^\s'\"]{4,})(['\"]?)"
        ),
        r"\1\2\3" + MASK + r"\5",
    ),
    # URL-embedded credentials: https://user:pass@host
    (re.compile(r"(?i)(https?://)([^/\s:@]+):([^/\s@]+)@"), r"\1\2:" + MASK + "@"),
]


def redact(text: str) -> str:
    """Mask secret-looking values in free text."""
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_obj(obj: Any) -> Any:
    """Recursively redact secrets inside dicts/lists/strings."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: (MASK if _sensitive_key(k) else redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj


_SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "api-key", "token", "github_token",
    "secret", "password", "passwd", "pwd", "client_secret", "private_key",
    "foundry_api_key", "openai_api_key", "cookie", "set-cookie",
}


def _sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    k = key.lower().replace("-", "_")
    return k in _SENSITIVE_KEYS or k.endswith(("_token", "_secret", "_password", "_key")) and k not in {
        "public_key", "monkey", "turkey",
    }
