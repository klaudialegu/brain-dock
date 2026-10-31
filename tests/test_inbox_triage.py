"""The triage page (harness PR 5b): approve once, reject with a listed reason code, never
while an agent runs; the review page and the rejection log show reason codes; a missing
config is reported on the page, never a crash; the demo loader never touches the real
database."""

import hashlib
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from brain_dock import registry
from brain_dock.core import db
from brain_dock.core.agents import guard
from brain_dock.core.agents.approvals import create_approval
from brain_dock.core.agents.run_tables import Approval, WorkItem
from brain_dock.core.app import create_app
from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.inbox import config, demo
from brain_dock.modules.inbox.models import InboxRole

from .conftest import BASE_URL
from .inbox_support import FAKE_CITY, FAKE_FLOOR, KEY, run_fixtures, write_config


@pytest.fixture(autouse=True)
def configured(tmp_path, monkeypatch):
    """Fake thresholds where the page looks for config.toml (never the repo's own)."""
    monkeypatch.setattr(config, "DEFAULT_PATH", write_config(tmp_path))


@pytest.fixture
def client(tmp_path):
    run_fixtures(tmp_path)  # 2 suggestions waiting, 3 skipped, 5 roles and 1 email parked
    with TestClient(create_app(registry.installed()), base_url=BASE_URL) as client:
        yield client


def csrf(page: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def pending_ids(page: str) -> list[int]:
    return [int(n) for n in re.findall(r'action="/inbox/approvals/(\d+)/approve"', page)]


def post(client, path, **data):
    page = client.get("/inbox").text
    return client.post(
        path,
        data={"csrf_token": csrf(page), **data},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )


def approval(approval_id):
    engine = get_engine()
    with Session(engine) as session:
        a = session.get(Approval, approval_id)
        item = session.get(WorkItem, a.item_id) if a.item_id else None
        result = a.status, a.reason, item.state if item else None
    engine.dispose()
    return result


def test_triage_page_lists_pending_suggestions(client):
    page = client.get("/inbox").text

    assert len(pending_ids(page)) == 2
    # Display names come from the first email that named the role (here, the digest).
    assert "Sr. Forward Deployed Engineer" in page and "Illustrative Inc" in page
    assert "USD 140,000–190,000 / year" in page and "up to 175,000" in page
    assert "2 emails" in page  # the duplicated role was seen in two alerts
    assert 'href="https://jobs.example.com/view/101"' in page  # tracking already stripped
    assert "Sample Systems" not in page  # skipped by rules: in the log, not waiting for me


def test_approve_button_runs_the_approval_once(client):
    first = pending_ids(client.get("/inbox").text)[0]

    once = post(client, f"/inbox/approvals/{first}/approve")
    twice = post(client, f"/inbox/approvals/{first}/approve")

    assert once.status_code == 303 and once.headers["location"] == "/inbox?done=approved"
    assert twice.headers["location"] == "/inbox?done=refused"
    assert approval(first) == ("executed", None, "approved")
    engine = get_engine()
    with Session(engine) as session:
        assert len(session.exec(select(InboxRole).where(InboxRole.status == "accepted")).all()) == 1
    engine.dispose()
    page = client.get("/inbox?done=approved").text
    assert "Accepted." in page and first not in pending_ids(page)


def test_reject_accepts_only_listed_reason_codes(client):
    first = pending_ids(client.get("/inbox").text)[0]

    free_text = post(client, f"/inbox/approvals/{first}/reject", reason="I just don't like it")
    unknown = post(client, f"/inbox/approvals/{first}/reject", reason="made_up_code")
    assert free_text.status_code == unknown.status_code == 400
    assert approval(first) == ("pending", None, "pending_approval")

    listed = post(client, f"/inbox/approvals/{first}/reject", reason="not_a_fit")

    assert listed.headers["location"] == "/inbox?done=rejected"
    assert approval(first) == ("rejected", "not_a_fit", "rejected")


def test_approve_is_refused_while_a_run_is_active(client, monkeypatch):
    first = pending_ids(client.get("/inbox").text)[0]
    page = client.get("/inbox").text
    monkeypatch.setattr(guard, "_runs", [{"allow": (), "on_refusal": None}])  # a run is on

    response = client.post(
        f"/inbox/approvals/{first}/approve",
        data={"csrf_token": csrf(page)},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/inbox?done=refused"
    assert approval(first) == ("pending", None, "pending_approval")


def test_review_page_shows_reason_codes_only(client):
    page = client.get("/inbox/review").text

    for code in ("missing_salary", "missing_location", "missing_seniority", "salary_no_top"):
        assert f"<code>{code}</code>" in page, code
    assert "<code>no_roles_found</code>" in page  # the email with no roles, parked
    assert page.count("<tr>") == 5 + 1 + 2  # 5 roles, 1 email, 2 header rows
    for leaked in (FAKE_CITY, FAKE_FLOOR, "150,000", "Traceback", "Error"):
        assert leaked not in page, leaked


def test_rejection_log_counts_reason_codes(client):
    for approval_id in pending_ids(client.get("/inbox").text):
        post(client, f"/inbox/approvals/{approval_id}/reject", reason="not_a_fit")

    page = client.get("/inbox").text
    log = page[page.index('id="log-heading"') :]

    assert re.search(r"<td>Me</td>\s*<td>Not a fit <code>not_a_fit</code></td>\s*<td>2</td>", log)


def test_rejection_log_includes_rule_skips_with_their_reason_codes(client):
    page = client.get("/inbox").text
    log = page[page.index('id="log-heading"') :]

    rows = re.findall(
        r"<td>(Me|Rules)</td>\s*<td>[^<]*<code>(\w+)</code></td>\s*<td>(\d+)</td>", log
    )
    assert rows == [("Rules", "location_mismatch", "2"), ("Rules", "salary_below_floor", "1")]


@pytest.mark.parametrize("text", [None, "[inbox]\nlocations = []\n"], ids=["missing", "broken"])
def test_triage_page_says_when_rules_are_not_configured(client, tmp_path, monkeypatch, text):
    path = tmp_path / "elsewhere" / "config.toml"
    if text is not None:
        path.parent.mkdir()
        path.write_text(text)
    monkeypatch.setattr(config, "DEFAULT_PATH", path)

    page = client.get("/inbox").text

    assert "Rules aren't set up" in page
    assert ("config.toml not found" if text is None else "inbox.") in page
    assert len(pending_ids(page)) == 2  # what's already waiting can still be decided


def test_the_app_starts_without_inbox_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_PATH", write_config(tmp_path, "[other]\nx = 1\n"))
    engine = get_engine()
    migrate(engine)
    engine.dispose()

    with TestClient(create_app(registry.installed()), base_url=BASE_URL) as client:
        home = client.get("/applications")
        inbox = client.get("/inbox")

    assert home.status_code == inbox.status_code == 200
    assert "has no [inbox] section" in inbox.text


def test_triage_forms_only_decide_inbox_approvals(client):
    engine = get_engine()
    other = create_approval(
        engine, KEY, run_id="r", module="job_search", item_id=None, tool="t", raw_input={"x": 1}
    )
    engine.dispose()

    approved = post(client, f"/inbox/approvals/{other.id}/approve")
    rejected = post(client, f"/inbox/approvals/{other.id}/reject", reason="not_a_fit")

    assert approved.status_code == rejected.status_code == 404
    assert approval(other.id)[:2] == ("pending", None)


def test_inbox_demo_writes_only_the_demo_database(tmp_path):
    real = db.DB_PATH  # the test's stand-in for data/brain_dock.db (conftest)
    engine = get_engine()
    migrate(engine)
    engine.dispose()
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    demo_db = tmp_path / "demo" / "demo.db"

    assert "isn't ready" in demo.load_demo(demo_db)  # no file: nothing created
    assert not demo_db.exists()
    demo_db.parent.mkdir()
    engine = get_engine(f"sqlite:///{demo_db}")
    migrate(engine)
    engine.dispose()

    message = demo.load_demo(demo_db)

    assert (
        message.startswith("Loaded 5 demo emails") and "pending_approval 3" in message
    )  # example floor
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before
