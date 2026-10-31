"""The inbox rules (decision 4): only a present field that clearly fails skips; a missing or
unclear field goes to review; a clear miss wins over a missing field; salary compares the
top of the range; Remote and Hybrid – <city> are real locations."""

from dataclasses import dataclass, replace

import pytest

from brain_dock.modules.inbox.config import load_config
from brain_dock.modules.inbox.parser import parse_email
from brain_dock.modules.inbox.rules import Decision, decide

from .inbox_support import FAKE_CONFIG, alert, role_block, run_emails, run_fixtures, write_config


@dataclass(frozen=True)
class Role:
    location_kind: str | None = "remote"
    location_city: str | None = None
    seniority: str | None = "senior"
    salary_max: int | None = 190000
    salary_currency: str | None = "USD"
    salary_period: str | None = "year"


GOOD = Role()


@pytest.fixture
def config(tmp_path):
    return load_config(write_config(tmp_path))


def from_alert(**fields) -> Role:
    """A role as the parser reads it, so the rules see real parsed values."""
    (parsed,) = parse_email(alert(role_block(**fields))).roles
    location, salary = parsed.location, parsed.salary
    return Role(
        location.kind if location else None,
        location.city if location else None,
        parsed.seniority,
        salary.max if salary else None,
        salary.currency if salary else None,
        salary.period if salary else None,
    )


@pytest.mark.parametrize(
    "role, reason",
    [
        pytest.param(
            replace(GOOD, location_kind="onsite", location_city="faraway town"),
            "location_mismatch",
            id="location",
        ),
        pytest.param(replace(GOOD, seniority="junior"), "seniority_mismatch", id="seniority"),
        pytest.param(
            replace(GOOD, salary_max=120000), "salary_below_floor", id="salary_below_floor"
        ),
    ],
)
def test_a_clear_miss_is_skipped_by_rules(config, role, reason):
    assert decide(role, config) == Decision("skip", reason)


@pytest.mark.parametrize(
    "role, reason",
    [
        pytest.param(from_alert(salary="Competitive"), "missing_salary", id="salary"),
        pytest.param(from_alert(location=""), "missing_location", id="location"),
        pytest.param(
            from_alert(title="Forward Deployed Engineer"), "missing_seniority", id="seniority"
        ),
    ],
)
def test_missing_data_goes_to_needs_review_never_skipped(config, role, reason):
    assert decide(role, config) == Decision("review", reason)


def test_a_clear_miss_wins_over_a_missing_field(config):
    role = replace(GOOD, location_kind="onsite", location_city="faraway town", salary_currency=None)

    assert decide(replace(GOOD, salary_currency=None), config).outcome == "review"
    assert decide(role, config) == Decision("skip", "location_mismatch")


@pytest.mark.parametrize(
    "salary, reason",
    [
        pytest.param(
            "EUR 200,000 - 250,000 per year", "salary_other_currency", id="other_currency"
        ),
        pytest.param("USD 90 - 120 per hour", "salary_not_annual", id="not_annual"),
    ],
)
def test_unclear_salary_goes_to_needs_review(config, salary, reason):
    assert decide(from_alert(salary=salary), config) == Decision("review", reason)


@pytest.mark.parametrize(
    "top, outcome",
    [
        pytest.param(150000, "pass", id="top_at_floor_passes"),
        pytest.param(149999, "skip", id="top_below_floor_skips"),
    ],
)
def test_salary_floor_boundary(config, top, outcome):
    assert decide(replace(GOOD, salary_max=top), config).outcome == outcome


@pytest.mark.parametrize(
    "salary, expected",
    [
        pytest.param(
            "USD 120,000 - 160,000 per year", Decision("pass"), id="straddles_floor_passes"
        ),
        pytest.param("USD 150,000 per year", Decision("pass"), id="single_value_is_the_top"),
        pytest.param(
            "up to USD 149,000 per year",
            Decision("skip", "salary_below_floor"),
            id="up_to_value_is_the_top",
        ),
        pytest.param(
            "from USD 200,000 per year",
            Decision("review", "salary_no_top"),
            id="open_ended_goes_to_review",
        ),
    ],
)
def test_salary_compares_the_top_of_the_range(config, salary, expected):
    assert decide(from_alert(salary=salary), config) == expected


@pytest.mark.parametrize(
    "location, expected, locations",
    [
        pytest.param("Remote", Decision("pass"), None, id="remote_listed_passes"),
        pytest.param(
            "Remote",
            Decision("skip", "location_mismatch"),
            '["Example City"]',
            id="remote_not_listed_skips",
        ),
        pytest.param(
            "Hybrid – Example City", Decision("pass"), None, id="hybrid_listed_city_passes"
        ),
        pytest.param(
            "Hybrid – Faraway Town",
            Decision("skip", "location_mismatch"),
            None,
            id="hybrid_other_city_skips",
        ),
    ],
)
def test_remote_and_hybrid_locations_are_matched(tmp_path, location, expected, locations):
    text = FAKE_CONFIG
    if locations is not None:
        text = text.replace('["remote", "Example City"]', locations)
    config = load_config(write_config(tmp_path, text))

    assert decide(from_alert(location=location), config) == expected


def test_a_skipped_role_keeps_its_reason_code(tmp_path):
    stored = run_fixtures(tmp_path)

    skipped = {r.company: r.reason for r in stored if r.status == "skipped"}
    assert skipped == {
        "Sample Systems": "location_mismatch",
        "Demo Data LLC": "salary_below_floor",
        "Specimen Software": "location_mismatch",
    }


def test_a_role_that_passes_every_rule_is_suggested(config, tmp_path):
    assert decide(from_alert(), config) == Decision("pass")

    (role,) = run_emails(tmp_path, [alert(role_block())])

    assert (role.status, role.reason) == ("suggested", None)
