"""Masking free text before it can leave this machine (ADR 0013, 0015).

scrub() replaces anything secret-shaped with "[secret]", then runs the gateway's redact()
(emails, phone numbers, URL query strings). Call it on the raw text, before any cleaning
or trimming: those can remove the "@", "=" or "_" a shape needs, or cut an address in
half, and the masking would no longer see it. It's safe to call more than once.
"""

import re

from brain_dock.core.agents.gateway import redact

SHAPES = [
    re.compile(r"\b(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*\S+", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"),  # sk-ant-…, sk_… (ElevenLabs)
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),  # JWT
    re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}"),  # any long hex or base64 run
]


def scrub(text: str) -> str:
    for shape in SHAPES:
        text = shape.sub("[secret]", text)
    return redact(text).text
