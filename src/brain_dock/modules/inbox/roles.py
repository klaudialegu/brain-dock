"""A role's identity: normalized company, title, location and link (docs/design/
pr5-inbox-plan.md, "The role dedupe key"). When unsure, keep two roles apart: a duplicate
is one click to reject, a wrong merge hides a role."""

import json
import re
import unicodedata
from typing import NamedTuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LEGAL_SUFFIXES = frozenset({"inc", "llc", "ltd", "gmbh", "corp", "co"})
TITLE_WORDS = {"sr": "senior", "jr": "junior"}
# Dropped from links, matched without case. Anything else stays: an unfamiliar parameter
# might be the job id (gh_jid, jobId), and keeping it can only cause a duplicate.
TRACKING_PARAMS = frozenset(
    {"trackingid", "refid", "trk", "trkinfo", "ref", "source", "src", "gclid", "fbclid"}
)


class RoleIdentity(NamedTuple):
    company: str
    title: str
    location: str
    link: str


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def normalize_company(value: str | None) -> str:
    words = normalize_text(value).split()
    # Every trailing suffix: "Example Corp" and "Example Corp, Inc." must agree.
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_title(value: str | None) -> str:
    return " ".join(TITLE_WORDS.get(w, w) for w in normalize_text(value).split())


def _is_tracking(name: str) -> bool:
    name = name.casefold()
    return name.startswith("utm_") or name in TRACKING_PARAMS


def normalize_link(value: str | None) -> str:
    """https, lowercase host without www., no fragment or trailing slash, no tracking
    parameters, the rest sorted. Anything that isn't a web link counts as missing."""
    try:
        parts = urlsplit((value or "").strip())
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.removeprefix("www.")
    if port not in (None, 80, 443):
        host = f"{host}:{port}"
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    )
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))


def role_identity(company: str, title: str, location: str, link: str | None) -> RoleIdentity:
    return RoleIdentity(
        normalize_company(company),
        normalize_title(title),
        normalize_text(location),
        normalize_link(link),
    )


def natural_key(identity: RoleIdentity) -> str:
    """What Items.key_for() hashes (with the local key) into the role's work-item key."""
    return json.dumps(list(identity), ensure_ascii=False)
