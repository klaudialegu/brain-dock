"""The inbox parser (harness PR 5a): alerts into roles; unreadable values become missing,
never a guess; only parsed fields are kept, never the body."""

import re

import pytest
from sqlalchemy import text

from brain_dock.core.agents.audit import AuditKey
from brain_dock.core.agents.runs import Items
from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.inbox.agent import receive_emails
from brain_dock.modules.inbox.parser import Location, Salary, parse_email, parse_location

from .inbox_support import FIXTURES, alert, fixture, role_block

ITEMS_KEY = AuditKey(b"k" * 32)


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'inbox.db'}")
    migrate(engine)
    yield engine
    engine.dispose()


def test_parses_a_synthetic_alert_into_roles():
    parsed = parse_email(fixture("alert_three_roles.eml"))
    first = parsed.roles[0]

    assert parsed.message_id == "<alert-001@jobs.example.com>" and parsed.synthetic
    assert first.title == "Senior Forward Deployed Engineer"
    assert first.company == "Example Corp Inc."
    assert first.location == Location("remote", None)
    assert first.seniority == "senior"
    assert first.salary == Salary(140000, 190000, "USD", "year")


def test_an_alert_with_several_roles_gives_one_role_each():
    parsed = parse_email(fixture("alert_three_roles.eml"))

    assert [r.company for r in parsed.roles] == [
        "Example Corp Inc.",
        "Sample Systems",
        "Demo Data LLC",
    ]


@pytest.mark.parametrize(
    "block, field",
    [
        pytest.param(role_block(salary="Competitive"), "salary", id="salary_competitive"),
        pytest.param(
            role_block(salary="160,000 - 190,000 per year"), "salary", id="salary_no_currency"
        ),
        pytest.param(role_block(location=""), "location", id="location_blank"),
        pytest.param(role_block(location="Hybrid"), "location", id="hybrid_without_city"),
        pytest.param(
            role_block(title="Forward Deployed Engineer"), "seniority", id="no_seniority_word"
        ),
    ],
)
def test_unreadable_values_become_missing_not_guessed(block, field):
    (role,) = parse_email(alert(block)).roles

    assert getattr(role, field) is None
    others = {"salary", "location", "seniority"} - {field}
    assert all(getattr(role, f) is not None for f in others)  # only that field is missing


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param("Remote", Location("remote", None), id="remote"),
        pytest.param(
            "Hybrid – Example City", Location("hybrid", "example city"), id="hybrid_en_dash_city"
        ),
        pytest.param(
            "Hybrid - Example City", Location("hybrid", "example city"), id="hybrid_hyphen_city"
        ),
        pytest.param("Example City", Location("onsite", "example city"), id="plain_city"),
    ],
)
def test_location_formats_are_read_not_missing(value, expected):
    assert parse_location(value) == expected
    (role,) = parse_email(alert(role_block(location=value))).roles
    assert role.location == expected


def test_an_email_with_no_roles_is_parked_not_dropped(engine):
    keys = receive_emails(engine, Items(engine, ITEMS_KEY), [fixture("alert_no_roles.eml")])

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT status, reason, role_count FROM inbox_email"))
        assert list(map(tuple, rows)) == [("needs_review", "no_roles_found", 0)]
    assert keys == []


def test_email_bodies_are_not_stored(engine):
    raw = fixture("alert_three_roles.eml")
    receive_emails(engine, Items(engine, ITEMS_KEY), [raw])

    with engine.connect() as connection:
        dump = "\n".join(connection.connection.iterdump())
    assert "inbox_role" in dump  # the dump covers the inbox tables
    for leftover in ("alert-001", "3 new roles for you", "candidate@example.org", "utm_source"):
        assert leftover not in dump, leftover  # no Message-ID, subject, address or tracking


RESERVED = re.compile(
    r"(^|\.)(example\.(com|org|net)|[a-z0-9-]+\.(test|invalid|example|localhost))$"
)


def test_fixtures_are_synthetic_and_use_reserved_domains():
    files = sorted(FIXTURES.glob("*.eml"))

    assert len(files) >= 5  # the check covers real fixtures
    for path in files:
        content = path.read_text()
        assert parse_email(content).synthetic, f"{path.name} needs X-Synthetic: true"
        hosts = re.findall(r"[\w.+-]+@([\w.-]+)", content)
        hosts += re.findall(r"https?://([\w.-]+)", content)
        assert hosts, path.name
        for host in hosts:
            assert RESERVED.search(host.lower()), f"{path.name}: {host} isn't a reserved domain"
