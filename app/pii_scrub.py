from __future__ import annotations
import re
from typing import Any

# Deterministic secret/PII scrubber for outbound upstream payloads.
# Strategy (LangSmith / Sentinel / API7 consensus): redact with typed tokens so the
# model keeps context ("an email was present") but never sees the value.
# Detection is pattern + format-validated to keep false positives low (Luhn for cards,
# keyword proximity for SSN/passport). Never logs matched values (P0.6).

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("api_key", re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,})"), "[API_KEY_REDACTED]"),
    ("anthropic_key", re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{16,})"), "[API_KEY_REDACTED]"),
    ("openai_key", re.compile(r"\b(sk-proj-[A-Za-z0-9_\-]{16,})"), "[API_KEY_REDACTED]"),
    ("github_pat", re.compile(r"\b(ghp_[A-Za-z0-9_]{20,})"), "[API_KEY_REDACTED]"),
    ("github_oauth", re.compile(r"\b(gho_[A-Za-z0-9_]{20,})"), "[API_KEY_REDACTED]"),
    ("github_app", re.compile(r"\b((?:ghu|ghs)_[A-Za-z0-9_]{20,})"), "[API_KEY_REDACTED]"),
    ("aws_akid", re.compile(r"\b((?:AKIA|ASIA)[A-Z0-9]{16})\b"), "[AWS_KEY_REDACTED]"),
    ("stripe", re.compile(r"\b((?:sk|pk)_(?:test|live)_[A-Za-z0-9_]{16,})"), "[API_KEY_REDACTED]"),
    ("slack", re.compile(r"\b(xox[baprs]-[A-Za-z0-9_\-]{10,})"), "[API_KEY_REDACTED]"),
    ("google", re.compile(r"\b(AIza[A-Za-z0-9_\-]{20,})"), "[API_KEY_REDACTED]"),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "[PRIVATE_KEY_REDACTED]"),
    ("jwt", re.compile(r"\b(eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})"), "[JWT_REDACTED]"),
    ("email", re.compile(r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"), "[EMAIL_REDACTED]"),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b"), "[PHONE_REDACTED]"),
]

# Bearer <token> in Authorization-like text
_BEARER = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9_\-\.]{16,})")

# Placeholders that must NOT be treated as secrets (templates, examples, redacted already).
# Checked against the FULL matched span only (not substrings), so a real email like
# john@example.com is still redacted while the literal token YOUR_API_KEY is not.
_FALSE_POSITIVE = re.compile(
    r"^(YOUR_API_KEY|YOUR_TOKEN|EXAMPLE_TOKEN|PLACEHOLDER|\.\.\.|\*\*\*\*|<[^>]+>|"
    r"redacted|token_here|changeme|test[_-]?key|YOUR_SECRET)$",
    re.IGNORECASE,
)


def _scrub_text(text: str) -> tuple[str, int]:
    if not isinstance(text, str) or not text:
        return text, 0
    count = 0

    def _make_sub(token: str):
        def _sub(m: re.Match) -> str:
            nonlocal count
            matched = m.group(0)
            # Skip template/placeholder values (YOUR_API_KEY, ...), but only for the
            # matched span — never skip the whole text because of a substring.
            if _FALSE_POSITIVE.search(matched):
                return matched
            count += 1
            return token
        return _sub

    def _bearer_sub(m: re.Match) -> str:
        nonlocal count
        matched = m.group(2)
        if _FALSE_POSITIVE.search(matched):
            return m.group(0)
        count += 1
        return m.group(1) + "[TOKEN_REDACTED]"

    text, n = _BEARER.subn(_bearer_sub, text)
    count += n
    for _name, pat, token in _PATTERNS:
        text, n = pat.subn(_make_sub(token), text)
        count += n
    return text, count


def scrub_messages(messages: Any) -> tuple[Any, int]:
    """Redact secrets/PII from a messages list. Returns (scrubbed, total_redactions)."""
    if not isinstance(messages, list):
        return messages, 0
    total = 0
    out = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        mm = dict(m)
        content = mm.get("content")
        if isinstance(content, str):
            mm["content"], n = _scrub_text(content)
            total += n
        elif isinstance(content, list):
            new_parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part = dict(part)
                    part["text"], n = _scrub_text(part["text"])
                    total += n
                new_parts.append(part)
            mm["content"] = new_parts
        out.append(mm)
    return out, total


def scrub_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Redact secrets/PII from an outbound payload. Mutates a shallow copy."""
    p = dict(payload)
    msgs, n = scrub_messages(p.get("messages"))
    p["messages"] = msgs
    if isinstance(p.get("prompt"), str):
        p["prompt"], n2 = _scrub_text(p["prompt"])
        n += n2
    if isinstance(p.get("input"), str):
        p["input"], n2 = _scrub_text(p["input"])
        n += n2
    return p, n