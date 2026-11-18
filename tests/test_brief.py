"""The daily brief as text (ADR 0013): counts and dates only, capped, from enabled modules."""

import socket
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from brain_dock import brief, registry
from brain_dock.core.agents.run_tables import Approval
from brain_dock.modules.inbox.brief import brief_lines as inbox_lines
from brain_dock.modules.job_search.brief import brief_lines as job_lines
from brain_dock.modules.job_search.models import (
    create_application,
    get_or_create_company,
    record_stage,
    save_interested,
)

TODAY = date(2026, 11, 17)


def add(session, company, *, stage=None, follow_up_on=None, **fields):
    app = create_application(
        session,
        get_or_create_company(session, company),
        fields.pop("role", "Engineer"),
        "support",
        TODAY - timedelta(days=20),
        follow_up_on=follow_up_on,
        **fields,
    )
    if stage:
        record_stage(session, app, stage, TODAY - timedelta(days=5))
    session.commit()
    return app


def pending_approval(session, status="pending"):
    session.add(
        Approval(
            run_id="r1",
            module="inbox",
            tool="t",
            input_json="{}",
            input_mac="m",
            status=status,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()


def test_job_search_brief_counts_follow_ups_and_active_stages(session):
    add(session, "A", follow_up_on=TODAY)
    add(session, "B", follow_up_on=TODAY, stage="screen")
    add(session, "C", follow_up_on=TODAY - timedelta(days=2), stage="interview")
    add(session, "D", stage="offer")
    add(session, "E", stage="rejected", follow_up_on=TODAY)  # closed: never counted
    save_interested(session, get_or_create_company(session, "F"), "Role", "fde", TODAY)
    session.commit()

    assert job_lines(session, TODAY) == [
        "2 follow-ups are due today.",
        "1 follow-up is overdue.",
        "In progress: 1 applied, 1 screen, 1 interview.",
        "1 offer is open.",
        "1 saved job is waiting to be applied to.",
    ]


def test_inbox_brief_counts_waiting_roles(session):
    assert inbox_lines(session, TODAY) == []
    pending_approval(session)
    pending_approval(session)
    pending_approval(session, status="rejected")  # decided: not waiting

    assert inbox_lines(session, TODAY) == ["2 inbox roles are waiting for your decision."]


def test_brief_never_names_companies_roles_notes_or_links(session):
    planted = ["Zyxcorp", "Quillwright Analyst", "note-qwfp", "https://jobs.example/qwfp"]
    add(
        session,
        planted[0],
        role=planted[1],
        notes=planted[2],
        link=planted[3],
        follow_up_on=TODAY,
        stage="interview",
    )
    save_interested(
        session,
        get_or_create_company(session, "Vexmoor"),
        "Plinth Lead",
        "fde",
        TODAY,
        notes="saved-note-qwfp",
        link="https://jobs.example/vex",
    )
    session.commit()

    text = brief.build_brief(session, TODAY, registry.installed())

    assert "1 follow-up is due today." in text  # the data was read
    for value in [*planted, "Vexmoor", "Plinth Lead", "saved-note-qwfp", "jobs.example"]:
        assert value.lower() not in text.lower()


def test_brief_with_nothing_due_says_so(session):
    text = brief.build_brief(session, TODAY, registry.installed())

    assert text == (
        "Good morning. Here's your brief for Tuesday, November 17. "
        "Nothing needs your attention today."
    )


def test_brief_is_capped_and_drops_whole_lines():
    lines = [f"Line number {i} has some words in it." for i in range(40)]

    text = brief.cap(lines, limit=120)

    assert len(text) <= 120
    assert text.endswith(brief.CLOSING)
    kept = text.removesuffix(" " + brief.CLOSING)
    assert kept == " ".join(lines[: kept.count("Line number")])  # whole lines, in order
    assert brief.cap(lines[:2]) == " ".join(lines[:2])  # under the cap: unchanged


def test_brief_uses_only_enabled_modules(session):
    pending_approval(session)
    job_search = registry.INSTALLED["job_search"]
    loud = replace(job_search, brief=lambda s, d: ["From job search."])

    text = brief.build_brief(session, TODAY, [loud])

    assert "From job search." in text
    assert "inbox" not in text  # the inbox isn't enabled, so its waiting role isn't read
    assert "waiting" in brief.build_brief(session, TODAY, registry.installed())


def test_brief_command_prints_and_sends_nothing(monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError("the brief command must not touch the network")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(brief, "current_brief", lambda: "Good morning. Test brief.")

    assert brief.main() == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "Good morning. Test brief.",
        "(25 characters; nothing was sent anywhere)",
    ]
