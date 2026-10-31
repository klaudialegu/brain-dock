"""The role dedupe key (docs/design/pr5-inbox-plan.md): normalized company, title, location
and link. When unsure, keep roles apart: a duplicate is one click, a merge hides a role."""

import hashlib

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from brain_dock.core.agents.audit import AuditKey
from brain_dock.core.agents.run_tables import WorkItem
from brain_dock.core.agents.runs import Items
from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.inbox.agent import receive_emails
from brain_dock.modules.inbox.models import InboxRole, InboxRoleSource
from brain_dock.modules.inbox.roles import natural_key, normalize_link, role_identity

from .inbox_support import alert, fixture, role_block

KEY = AuditKey(b"k" * 32)
BASE = (
    "Example Corp",
    "Senior Forward Deployed Engineer",
    "Remote",
    "https://jobs.example.com/view/1",
)


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'inbox.db'}")
    migrate(engine)
    yield engine
    engine.dispose()


def receive(engine, *emails):
    return receive_emails(engine, Items(engine, KEY), emails)


def roles(engine):
    with Session(engine) as session:
        return session.exec(select(InboxRole)).all()


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param(
            ("  EXAMPLE   corp ", "senior forward-deployed engineer", "REMOTE", BASE[3]),
            id="case_and_spaces",
        ),
        pytest.param(
            ("Example Corp, Inc.", "Sr. Forward Deployed Engineer", "Remote", BASE[3]),
            id="company_suffix",
        ),
        pytest.param(
            (*BASE[:3], "https://jobs.example.com/view/1/#apply"), id="fragment_and_trailing_slash"
        ),
        pytest.param((*BASE[:3], "http://www.Jobs.Example.com/view/1"), id="scheme_and_www"),
    ],
)
def test_role_key_normalizes(variant):
    assert role_identity(*variant) == role_identity(*BASE)


@pytest.mark.parametrize(
    "param",
    ["utm_source=alert&utm_medium=email", "trackingId=abc123", "refId=xyz", "trk=jobs", "gclid=g1"],
    ids=["utm_prefix", "trackingId", "refId", "trk", "gclid"],
)
def test_link_drops_tracking_params(param):
    assert (
        normalize_link(f"https://jobs.example.com/view/1?{param}")
        == "https://jobs.example.com/view/1"
    )


@pytest.mark.parametrize(
    "param",
    ["gh_jid=303", "jobId=42", "currentJobId=7", "team=support"],
    ids=["gh_jid", "jobId", "currentJobId", "unknown_param"],
)
def test_link_keeps_identifying_and_unknown_params(param):
    link = f"https://jobs.example.com/view?{param}&utm_source=alert"

    assert normalize_link(link) == f"https://jobs.example.com/view?{param}"


GH_BASE = (*BASE[:3], "https://boards.example.com/jobs?gh_jid=1")


@pytest.mark.parametrize(
    "one, other",
    [
        pytest.param(BASE, (BASE[0], "Senior Solutions Engineer", *BASE[2:]), id="title"),
        pytest.param(BASE, (*BASE[:2], "Hybrid – Example City", BASE[3]), id="location"),
        pytest.param(BASE, (*BASE[:3], "https://jobs.example.com/view/2"), id="link"),
        pytest.param(BASE, ("Sample Systems", *BASE[1:]), id="company"),
        pytest.param(
            GH_BASE,
            (*BASE[:3], "https://boards.example.com/jobs?gh_jid=2"),
            id="job_id_query_param",
        ),
    ],
)
def test_role_key_keeps_different_roles_apart(one, other):
    assert role_identity(*one) != role_identity(*other)


def test_the_same_role_in_two_emails_is_one_item_with_both_sources_linked(engine):
    first = receive(engine, fixture("alert_three_roles.eml"))
    second = receive(engine, fixture("alert_duplicate_role.eml"))

    assert second[0].value == first[0].value  # the same work-item key
    (role,) = [r for r in roles(engine) if r.title_key.endswith("forward deployed engineer")]
    with Session(engine) as session:
        sources = session.exec(select(InboxRoleSource).where(InboxRoleSource.role_id == role.id))
        assert len(sources.all()) == 2
    assert len(roles(engine)) == 3


def test_the_same_email_twice_changes_nothing(engine):
    receive(engine, fixture("alert_three_roles.eml"))
    with engine.connect() as connection:
        before = "\n".join(connection.connection.iterdump())

    again = receive(engine, fixture("alert_three_roles.eml"))

    with engine.connect() as connection:
        assert "\n".join(connection.connection.iterdump()) == before
    assert again == []


def test_a_missing_field_counts_as_empty_not_unique(engine):
    no_link = role_block(link="")
    receive(engine, alert(no_link, message_id="<a@jobs.example.com>"))
    receive(engine, alert(no_link, message_id="<b@jobs.example.com>"))  # same role, no link
    receive(engine, alert(role_block(), message_id="<c@jobs.example.com>"))  # with a link

    stored = roles(engine)
    assert len(stored) == 2 and sorted(r.link_key for r in stored)[0] == ""
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM inbox_role_source")).scalar() == 3


def test_role_item_keys_are_keyed_hashes(engine):
    (key,) = receive(engine, alert(role_block()))
    identity = role_identity(*BASE)
    plain = hashlib.sha256(natural_key(identity).encode()).hexdigest()

    assert key.value != plain
    assert key.value == Items(engine, KEY).key_for("inbox", natural_key(identity)).value
    assert (
        Items(engine, AuditKey(b"x" * 32)).key_for("inbox", natural_key(identity)).value
        != key.value
    )
    with Session(engine) as session:  # the role row points at exactly this key
        assert session.exec(select(InboxRole.item_key)).one() == key.value
        assert session.exec(select(WorkItem)).all() == []  # receiving alone starts no work
