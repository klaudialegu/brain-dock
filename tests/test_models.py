from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from brain_dock.modules.job_search.models import (
    Application,
    Company,
    RoleTrack,
    Stage,
    StageEvent,
    create_application,
    record_stage,
)


@pytest.fixture
def acme(session):
    company = Company(name="Acme Analytics")
    session.add(company)
    session.commit()
    return company


@pytest.fixture
def application(session, acme):
    app = create_application(session, acme, "Solutions Engineer", RoleTrack.fde, date(2026, 10, 1))
    session.commit()
    return app


def test_create_application_saves_all_fields(session, acme):
    app = create_application(
        session,
        acme,
        "Forward Deployed Engineer",
        RoleTrack.fde,
        date(2026, 10, 1),
        link="https://example.com/jobs/123",
        notes="Referred by a friend",
        follow_up_on=date(2026, 10, 8),
    )
    session.commit()
    session.refresh(app)

    assert app.id is not None
    assert app.company.name == "Acme Analytics"
    assert app.role_title == "Forward Deployed Engineer"
    assert app.role_track == RoleTrack.fde
    assert app.applied_on == date(2026, 10, 1)
    assert app.link == "https://example.com/jobs/123"
    assert app.notes == "Referred by a friend"
    assert app.follow_up_on == date(2026, 10, 8)


def test_new_application_starts_with_one_applied_event(application):
    assert application.current_stage == Stage.applied
    assert [(e.stage, e.happened_on) for e in application.events] == [
        (Stage.applied, date(2026, 10, 1))
    ]


def test_optional_fields_default_to_none(application):
    assert application.link is None
    assert application.notes is None
    assert application.follow_up_on is None


def test_unknown_role_track_is_rejected(session, acme):
    with pytest.raises(ValueError):
        create_application(session, acme, "Engineer", "astronaut", date(2026, 10, 1))


def test_record_stage_adds_event_and_advances_current_stage(session, application):
    record_stage(session, application, Stage.screen, date(2026, 10, 5), note="30 min call")
    session.commit()

    assert application.current_stage == Stage.screen
    assert [e.stage for e in application.events] == [Stage.applied, Stage.screen]
    assert application.events[-1].note == "30 min call"


def test_backdated_event_does_not_move_stage_backwards(session, application):
    record_stage(session, application, Stage.interview, date(2026, 10, 10))
    record_stage(session, application, Stage.screen, date(2026, 10, 5))  # backfilled
    session.commit()

    assert application.current_stage == Stage.interview


def test_same_day_events_latest_recorded_wins(session, application):
    record_stage(session, application, Stage.interview, date(2026, 10, 10))
    record_stage(session, application, Stage.rejected, date(2026, 10, 10))
    session.commit()

    assert application.current_stage == Stage.rejected


def test_stage_is_stored_as_readable_text(session, application):
    record_stage(session, application, Stage.screen, date(2026, 10, 5))
    session.commit()

    stored = session.connection().exec_driver_sql("SELECT current_stage FROM application")
    assert stored.scalar() == "screen"


def test_company_with_two_applications(session, acme):
    first = create_application(session, acme, "Support Engineer", "support", date(2026, 9, 1))
    second = create_application(session, acme, "Solutions Engineer", "fde", date(2026, 10, 1))
    session.commit()

    assert {a.role_title for a in acme.applications} == {"Support Engineer", "Solutions Engineer"}
    assert first.company is acme and second.company is acme


def test_duplicate_company_name_is_rejected(session, acme):
    session.add(Company(name="Acme Analytics"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_keys_are_enforced(session):
    result = session.connection().exec_driver_sql("PRAGMA foreign_keys")
    assert result.scalar() == 1


def test_application_for_missing_company_is_rejected(session):
    session.add(
        Application(
            company_id=999,
            role_title="Engineer",
            role_track=RoleTrack.other,
            applied_on=date(2026, 10, 1),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_stage_event_for_missing_application_is_rejected(session):
    session.add(StageEvent(application_id=999, stage=Stage.screen, happened_on=date(2026, 10, 1)))

    with pytest.raises(IntegrityError):
        session.commit()


def test_all_stages_and_tracks():
    assert [s.value for s in Stage] == [
        "interested",
        "applied",
        "screen",
        "interview",
        "onsite",
        "offer",
        "rejected",
        "ghosted",
        "withdrawn",
    ]
    assert [t.value for t in RoleTrack] == ["support", "fde", "other"]
