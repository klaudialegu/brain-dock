"""The inbox agent end to end, rules only (harness PR 5a): suggestions wait for approval,
approving writes only inbox data (ADR 0011), every email ends somewhere, and my thresholds
never reach the core's tables, the audit log or logs."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from brain_dock import registry
from brain_dock.core.agents.approvals import Approvals
from brain_dock.core.agents.audit import AuditLog
from brain_dock.core.agents.run_tables import Approval, WorkItem
from brain_dock.core.app import create_app
from brain_dock.core.db import get_engine
from brain_dock.modules.inbox.agent import make_workflow, receive_emails
from brain_dock.modules.inbox.config import load_config
from brain_dock.modules.inbox.models import InboxEmail, InboxRole

from .conftest import BASE_URL
from .inbox_support import (
    FAKE_CITY,
    FAKE_FLOOR,
    INBOX,
    all_fixtures,
    app_key,
    make_runner,
    migrate_app_db,
    run_fixtures,
    write_config,
)


@pytest.fixture
def inbox_db():
    migrate_app_db()


def table_rows(engine, prefix):
    with engine.connect() as connection:
        names = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE :p"),
            {"p": prefix + "%"},
        ).scalars()
        return {
            n: [tuple(r) for r in connection.execute(text(f"SELECT * FROM {n}"))] for n in names
        }


def test_inbox_workflow_definition_is_sound(tmp_path):
    config = load_config(write_config(tmp_path))

    assert make_workflow(config, None).problems() == []


def test_a_suggestion_waits_for_approval_and_nothing_is_written(inbox_db, tmp_path):
    stored = run_fixtures(tmp_path)
    engine = get_engine()

    suggested = sorted(r.company for r in stored if r.status == "suggested")
    # Fixtures load by file name, so the digest names the duplicated role first.
    assert suggested == ["Example Corp", "Illustrative Inc"]
    with Session(engine) as session:
        approvals = session.exec(select(Approval)).all()
        waiting = session.exec(select(WorkItem).where(WorkItem.state == "pending_approval"))
        assert len(waiting.all()) == 2
    assert [a.status for a in approvals] == ["pending", "pending"]
    assert all(r.status != "accepted" for r in stored)  # nothing ran without me


def test_accepting_writes_only_inbox_data(inbox_db, tmp_path):
    run_fixtures(tmp_path)
    engine = get_engine()
    with engine.begin() as connection:  # job search holds data that must stay as it is
        connection.exec_driver_sql("INSERT INTO company (name) VALUES ('Example Corp')")
    with Session(engine) as session:
        first = session.exec(select(Approval).order_by(Approval.id)).first()
    job_search_before = {t: table_rows(engine, t) for t in ("company", "application", "stageevent")}

    approvals = Approvals(engine, AuditLog(engine, app_key()), [INBOX], lambda: tmp_path)
    result = approvals.approve(first.id)
    again = approvals.approve(first.id)

    assert result.ok and not again.ok  # once, and only once
    with Session(engine) as session:
        role = session.get(InboxRole, result.output["accepted"])
        item = session.get(WorkItem, first.item_id)
    assert role.status == "accepted" and item.state == "approved"
    assert {t: table_rows(engine, t) for t in job_search_before} == job_search_before


def test_every_email_ends_suggested_skipped_or_needs_review(inbox_db, tmp_path):
    stored = run_fixtures(tmp_path)
    engine = get_engine()

    with Session(engine) as session:
        emails = session.exec(select(InboxEmail)).all()
        items = {i.key: i for i in session.exec(select(WorkItem))}
    assert len(emails) == len(all_fixtures())
    for mail in emails:
        assert mail.status == "needs_review" or mail.role_count > 0
    assert len(items) == len(stored) == 10  # every role became exactly one work item
    resting = {"pending_approval", "skipped", "needs_review"}
    assert all(items[r.item_key].state in resting for r in stored)
    assert {r.status for r in stored} == {"suggested", "skipped", "needs_review"}
    for role in stored:  # the role's status and its work item agree
        state = items[role.item_key].state
        assert {"suggested": "pending_approval"}.get(role.status, role.status) == state
        assert role.status != "needs_review" or items[role.item_key].reason == role.reason


def test_decisions_leave_no_content_or_thresholds_in_core_tables_audit_or_logs(
    inbox_db, tmp_path, caplog
):
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app(registry.installed()), base_url=BASE_URL):  # the app's logging
        run_fixtures(tmp_path)
    engine = get_engine()

    core = repr(table_rows(engine, "core_"))
    assert "core_audit_event" in core and "core_work_item" in core  # really checked
    for value in (FAKE_CITY, FAKE_FLOOR, "150,000", "Example Corp", "Senior", "jobs.example.com"):
        assert value not in core, value
        assert value not in caplog.text, value


# --- Added while building 5a (reported in the PR) -----------------------------------------


def test_a_resumed_run_never_asks_twice_for_the_same_role(inbox_db, tmp_path):
    runner, engine = make_runner(tmp_path)
    config = load_config(write_config(tmp_path))
    keys = receive_emails(engine, runner.items, all_fixtures())
    workflow = make_workflow(config, engine)
    run_id = runner.start("inbox", 0)
    runner.run(workflow, run_id, keys)
    with engine.begin() as connection:  # as if a crash hit after asking, before moving on
        connection.exec_driver_sql(
            "UPDATE core_work_item SET state = 'ruled' WHERE state = 'pending_approval'"
        )
        connection.exec_driver_sql("UPDATE core_agent_run SET status = 'running'")

    runner.run(workflow, run_id)

    with Session(engine) as session:
        assert len(session.exec(select(Approval)).all()) == 2  # still one per role
        waiting = session.exec(select(WorkItem).where(WorkItem.state == "pending_approval"))
        assert len(waiting.all()) == 2
