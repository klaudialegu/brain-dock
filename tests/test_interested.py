"""The "interested" stage: a job saved before applying. It isn't an application yet, so
the list, the company page, the pipeline chart and the stats leave it out."""

import json
import re
from datetime import date

import pytest
from sqlmodel import Session, select

from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.job_search.export import export_applications
from brain_dock.modules.job_search.importer import ImportFileError, load_applications, rebuild_db
from brain_dock.modules.job_search.models import (
    Application,
    DateOrderError,
    NotAppliedError,
    RoleTrack,
    Stage,
    add_stage,
    create_application,
    get_or_create_company,
    mark_applied,
    record_stage,
    save_interested,
    update_application,
)
from brain_dock.modules.job_search.queries import (
    PipelineLink,
    company_detail,
    list_applications,
    pipeline_links,
    stats,
)

from .conftest import BASE_URL

TODAY = date(2026, 10, 31)
OLD = date(2026, 10, 1)  # old enough for the rates (30 days before TODAY)


def apply(session, role="Applied Role", applied=OLD, *stages):
    application = create_application(
        session, get_or_create_company(session, "Acme Analytics"), role, RoleTrack.fde, applied
    )
    for day, stage in enumerate(stages, start=2):
        record_stage(session, application, stage, applied.replace(day=day))
    session.commit()
    return application


def save(session, role="Saved Role", on=OLD, company="Acme Analytics"):
    application = save_interested(
        session, get_or_create_company(session, company), role, RoleTrack.fde, on
    )
    session.commit()
    return application


def edit(session, application, applied_on):
    update_application(
        session,
        application,
        company_name=application.company.name,
        role_title=application.role_title,
        role_track=application.role_track,
        applied_on=applied_on,
        link=None,
        notes=None,
        follow_up_on=None,
    )


# --- The model -------------------------------------------------------------------------


def test_saved_job_is_not_an_application_yet(session):
    saved = save(session)

    assert saved.applied_on is None
    assert saved.current_stage == Stage.interested
    assert [(e.stage, e.happened_on) for e in saved.events] == [(Stage.interested, OLD)]


def test_mark_applied_turns_it_into_an_application(session):
    saved = save(session, on=date(2026, 10, 5))

    mark_applied(session, saved, date(2026, 10, 5))  # same day: applied still wins
    session.commit()

    assert saved.applied_on == date(2026, 10, 5)
    assert saved.current_stage == Stage.applied
    assert [e.stage for e in sorted(saved.events, key=lambda e: e.id)] == [
        Stage.interested,
        Stage.applied,
    ]


def test_mark_applied_refuses_a_date_before_it_was_saved_or_a_second_time(session):
    saved = save(session, on=date(2026, 10, 5))

    with pytest.raises(DateOrderError):
        mark_applied(session, saved, date(2026, 10, 4))
    assert saved.applied_on is None and len(saved.events) == 1

    mark_applied(session, saved, date(2026, 10, 6))
    with pytest.raises(ValueError, match="already applied"):
        mark_applied(session, saved, date(2026, 10, 7))


def test_saved_job_cannot_be_edited_or_move_through_stages(session):
    saved = save(session)

    with pytest.raises(NotAppliedError):
        add_stage(session, saved, Stage.screen, date(2026, 10, 9))
    with pytest.raises(NotAppliedError):
        edit(session, saved, date(2026, 10, 9))
    assert saved.applied_on is None and len(saved.events) == 1


def test_editing_an_application_saved_first_respects_both_dates(session):
    application = save(session, on=date(2026, 10, 5))
    mark_applied(session, application, date(2026, 10, 7))
    session.commit()

    # Moving the applied date stays allowed while it's on or after the interested date.
    edit(session, application, date(2026, 10, 6))
    assert application.applied_on == date(2026, 10, 6)
    with pytest.raises(DateOrderError):
        edit(session, application, date(2026, 10, 4))


# --- What leaves saved jobs out ------------------------------------------------------------


def test_stats_leave_out_saved_jobs(session):
    apply(session, "Replied", OLD, Stage.screen)
    apply(session, "Silent", OLD)
    before = stats(session, TODAY)

    save(session, "Saved long ago", on=date(2026, 9, 1))
    save(session, "Saved today", on=TODAY)

    assert stats(session, TODAY) == before
    assert before.total == 2 and before.response_rate == 0.5


def test_pipeline_leaves_out_saved_jobs_and_starts_at_applied(session):
    apply(session, "Direct", OLD, Stage.screen)
    before = pipeline_links(session)
    save(session, "Only saved")
    then_applied = save(session, "Saved, then applied")
    mark_applied(session, then_applied, OLD)
    record_stage(session, then_applied, Stage.screen, date(2026, 10, 3))
    session.commit()

    links = {(link.source, link.target): link.count for link in pipeline_links(session)}

    assert before == [PipelineLink(Stage.applied, Stage.screen, 1)]
    assert links == {(Stage.applied, Stage.screen): 2}  # no Interested node anywhere


def test_list_and_company_page_leave_out_saved_jobs(session):
    applied = apply(session, "Applied Role")
    save(session, "Saved Role")

    assert [row.role_title for row in list_applications(session)] == ["Applied Role"]
    detail = company_detail(session, applied.company_id)
    assert [a.role_title for a in detail.applications] == ["Applied Role"]


def test_saved_job_has_no_edit_page_or_forms(client, session):
    saved = save(session)
    html = client.get("/applications/new").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    origin = {"Origin": BASE_URL}
    # Valid forms, so it's the saved job that stops them, not form validation.
    edit_form = {
        "csrf_token": token,
        "company": "Acme Analytics",
        "role_title": "Saved Role",
        "role_track": "fde",
        "applied_on": "2026-10-09",
    }
    stage_form = {"csrf_token": token, "stage": "screen", "happened_on": "2026-10-09"}

    responses = [
        client.get(f"/applications/{saved.id}/edit"),
        client.post(f"/applications/{saved.id}", data=edit_form, headers=origin),
        client.post(f"/applications/{saved.id}/stages", data=stage_form, headers=origin),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert saved.applied_on is None and len(saved.events) == 1


# --- Backups ---------------------------------------------------------------------------


SAVED_ENTRIES = [
    {
        "company": "Acme Analytics",
        "role_title": "Only saved",
        "role_track": "fde",
        "interested_on": "2026-09-01",
        "events": [],
    },
    {
        "company": "Acme Analytics",
        "role_title": "Saved, then applied",
        "role_track": "support",
        "interested_on": "2026-09-02",
        "applied_on": "2026-09-02",
        "events": [{"stage": "screen", "happened_on": "2026-09-05"}],
    },
    {
        "company": "Globex Systems",
        "role_title": "Saved, applied, nothing since",
        "role_track": "other",
        "interested_on": "2026-09-03",
        "applied_on": "2026-09-04",
        "events": [],
    },
]


def test_backups_keep_saved_jobs(tmp_path):
    source = tmp_path / "saved.json"
    source.write_text(json.dumps({"applications": SAVED_ENTRIES}))
    engine = get_engine(f"sqlite:///{tmp_path / 'saved.db'}")
    migrate(engine)

    rebuild_db(engine, load_applications(source), locked=False)
    with Session(engine) as session:
        assert export_applications(session) == {"applications": SAVED_ENTRIES}
        histories = {
            a.role_title: (a.current_stage, [e.stage for e in sorted(a.events, key=lambda e: e.id)])
            for a in session.exec(select(Application))
        }
    engine.dispose()

    assert histories == {
        "Only saved": (Stage.interested, [Stage.interested]),
        "Saved, then applied": (Stage.screen, [Stage.interested, Stage.applied, Stage.screen]),
        "Saved, applied, nothing since": (Stage.applied, [Stage.interested, Stage.applied]),
    }


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        ({}, "needs applied_on, or interested_on"),
        ({"interested_on": "2026-09-05", "applied_on": "2026-09-04"}, "interested_on is after"),
        (
            {
                "interested_on": "2026-09-01",
                "events": [{"stage": "screen", "happened_on": "2026-09-02"}],
            },
            "can't have stage events yet",
        ),
        (
            {
                "applied_on": "2026-09-01",
                "events": [{"stage": "interested", "happened_on": "2026-09-02"}],
            },
            '"interested" comes from interested_on',
        ),
    ],
    ids=["no-date", "saved-after-applied", "events-on-saved-job", "interested-as-event"],
)
def test_import_rules_for_saved_jobs(tmp_path, entry, problem):
    source = tmp_path / "bad.json"
    base = {"company": "Acme Analytics", "role_title": "Role", "role_track": "fde"}
    source.write_text(json.dumps({"applications": [base | entry]}))

    with pytest.raises(ImportFileError) as raised:
        load_applications(source)
    assert problem in str(raised.value.problems)
