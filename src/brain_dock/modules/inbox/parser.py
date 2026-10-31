"""Job-alert emails into roles. The synthetic alert format is one block per role, blocks
separated by a line of "---", each line "Field: value" (Role, Company, Location, Salary,
Link). Real alert formats come with real email (Phase 3b).

An unreadable value becomes missing, never a guess; the rules send missing data to review.
"""

import email
import email.policy
import re
from dataclasses import dataclass

from brain_dock.modules.inbox.roles import normalize_text, normalize_title

LEVELS = ("junior", "mid", "senior", "staff", "principal", "lead")
PERIODS = {"year": "year", "yr": "year", "month": "month", "mo": "month", "hour": "hour"}
SALARY = re.compile(
    r"(?:(?P<bound>up to|from)\s+)?(?P<currency>[A-Z]{3})\s+(?P<low>\d+)"
    r"(?:\s*[-–]\s*(?P<high>\d+))?\s*(?:per|/)\s*(?P<period>year|yr|month|mo|hour)",
)
HYBRID = re.compile(r"hybrid\s*(?:[-–—:,]\s*(?P<city>.*))?", re.IGNORECASE)


@dataclass(frozen=True)
class Salary:
    min: int | None
    max: int | None  # the top of the range; None for "from X"
    currency: str
    period: str


@dataclass(frozen=True)
class Location:
    kind: str  # remote | hybrid | onsite
    city: str | None  # normalized; None for remote


@dataclass(frozen=True)
class ParsedRole:
    title: str
    company: str
    location_text: str
    link: str
    location: Location | None
    seniority: str | None
    salary: Salary | None


@dataclass(frozen=True)
class ParsedEmail:
    message_id: str | None
    synthetic: bool
    roles: tuple[ParsedRole, ...]


def parse_salary(text: str | None) -> Salary | None:
    match = SALARY.fullmatch((text or "").replace(",", "").strip())
    if match is None:
        return None
    low = int(match["low"])
    high = int(match["high"]) if match["high"] else None
    period = PERIODS[match["period"]]
    if match["bound"] == "up to":
        return Salary(None, low, match["currency"], period)
    if match["bound"] == "from":
        return Salary(low, None, match["currency"], period)
    return Salary(low, high if high is not None else low, match["currency"], period)


def parse_location(text: str | None) -> Location | None:
    text = (text or "").strip()
    if not text:
        return None
    if normalize_text(text).split()[:1] == ["remote"]:
        return Location("remote", None)
    hybrid = HYBRID.fullmatch(text)
    if hybrid is not None:
        city = normalize_text(hybrid["city"])
        return Location("hybrid", city) if city else None
    return Location("onsite", normalize_text(text))


def parse_seniority(title: str | None) -> str | None:
    return next((w for w in normalize_title(title).split() if w in LEVELS), None)


def _blocks(body: str) -> list[dict[str, str]]:
    blocks, current = [], {}
    for line in body.splitlines():
        if line.strip() == "---":
            blocks.append(current)
            current = {}
        elif ":" in line:
            name, _, value = line.partition(":")
            current[name.strip().casefold()] = value.strip()
    blocks.append(current)
    return blocks


def parse_email(raw: str | bytes) -> ParsedEmail:
    # Always from bytes: from a str, the email package turns non-ASCII body text (an en
    # dash in "Hybrid – City") into a literal "\u2013".
    data = raw.encode() if isinstance(raw, str) else raw
    message = email.message_from_bytes(data, policy=email.policy.default)
    part = message.get_body(preferencelist=("plain",))
    body = part.get_content() if part is not None else ""
    roles = []
    for block in _blocks(body):
        title, company = block.get("role", ""), block.get("company", "")
        if not title or not company:
            continue
        roles.append(
            ParsedRole(
                title=title,
                company=company,
                location_text=block.get("location", ""),
                link=block.get("link", ""),
                location=parse_location(block.get("location")),
                seniority=parse_seniority(title),
                salary=parse_salary(block.get("salary")),
            )
        )
    message_id = (message.get("Message-ID") or "").strip() or None
    synthetic = (message.get("X-Synthetic") or "").strip().casefold() == "true"
    return ParsedEmail(message_id, synthetic, tuple(roles))
