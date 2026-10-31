"""Deterministic rules, in plain Python (design section 3): location, seniority, salary.

Only a field that is present and clearly fails can skip a role; a missing or unclear field
sends it to review. A clear miss wins over a missing field, because the miss is enough on
its own (docs/design/pr5-inbox-plan.md, decision 4).
"""

from dataclasses import dataclass
from typing import Protocol

from brain_dock.modules.inbox.config import InboxConfig

PASS, SKIP, REVIEW = "pass", "skip", "review"


class RoleFields(Protocol):
    location_kind: str | None
    location_city: str | None
    seniority: str | None
    salary_max: int | None
    salary_currency: str | None
    salary_period: str | None


@dataclass(frozen=True)
class Decision:
    outcome: str  # pass | skip | review
    reason: str | None = None


def _location(role: RoleFields, config: InboxConfig) -> Decision:
    if role.location_kind is None:
        return Decision(REVIEW, "missing_location")
    place = "remote" if role.location_kind == "remote" else role.location_city
    return Decision(PASS) if place in config.locations else Decision(SKIP, "location_mismatch")


def _seniority(role: RoleFields, config: InboxConfig) -> Decision:
    if role.seniority is None:
        return Decision(REVIEW, "missing_seniority")
    if role.seniority not in config.seniority:
        return Decision(SKIP, "seniority_mismatch")
    return Decision(PASS)


def _salary(role: RoleFields, config: InboxConfig) -> Decision:
    if role.salary_currency is None:
        return Decision(REVIEW, "missing_salary")
    if role.salary_currency != config.currency:
        return Decision(REVIEW, "salary_other_currency")  # no conversion, no guessing
    if role.salary_period != "year":
        return Decision(REVIEW, "salary_not_annual")
    if role.salary_max is None:
        return Decision(REVIEW, "salary_no_top")
    if role.salary_max < config.salary_floor:  # the top of the range decides
        return Decision(SKIP, "salary_below_floor")
    return Decision(PASS)


def decide(role: RoleFields, config: InboxConfig) -> Decision:
    checks = [check(role, config) for check in (_location, _seniority, _salary)]
    for outcome in (SKIP, REVIEW):
        found = next((d for d in checks if d.outcome == outcome), None)
        if found is not None:
            return found
    return Decision(PASS)
