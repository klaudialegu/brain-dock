from datetime import date

import pytest

from brain_dock.models import (
    RoleTrack,
    Stage,
    create_application,
    get_or_create_company,
    record_stage,
)
from brain_dock.queries import RESPONSE_MIN_AGE_DAYS, stats
from brain_dock.stages import INTERVIEW_STAGES, REPLY_STAGES

TODAY = date(2026, 10, 31)
OLD = date(2026, 10, 1)  # 30 days before TODAY


def add(session, applied_on=OLD, *stages):
    application = create_application(
        session, get_or_create_company(session, "Acme Analytics"), "Role", RoleTrack.fde, applied_on
    )
    for stage in stages:
        record_stage(session, application, stage, applied_on)
    session.commit()
    return application


def test_no_applications(session):
    result = stats(session, TODAY)

    assert result.total == 0
    assert result.response_rate is None and result.interview_rate is None
    assert result.days_since_last_application is None


def test_reply_and_interview_stage_definitions():
    assert REPLY_STAGES == {
        Stage.screen,
        Stage.interview,
        Stage.onsite,
        Stage.offer,
        Stage.rejected,
    }
    assert INTERVIEW_STAGES == {Stage.interview, Stage.onsite, Stage.offer}
    assert RESPONSE_MIN_AGE_DAYS == 14


def test_response_rate_counts_any_reply_but_not_ghosted_or_withdrawn(session):
    add(session, OLD, Stage.screen)
    add(session, OLD, Stage.rejected)
    add(session, OLD, Stage.ghosted)
    add(session, OLD, Stage.withdrawn)
    add(session, OLD)  # no reply yet

    result = stats(session, TODAY)

    assert (result.responded, result.old_enough) == (2, 5)
    assert result.response_rate == pytest.approx(0.4)


def test_response_rate_leaves_out_applications_younger_than_14_days(session):
    add(session, OLD, Stage.screen)
    add(session, date(2026, 10, 17))  # exactly 14 days old: counted
    add(session, date(2026, 10, 18), Stage.screen)  # 13 days old: left out, even with a reply

    result = stats(session, TODAY)

    assert (result.responded, result.old_enough) == (1, 2)
    assert result.response_rate == pytest.approx(0.5)


def test_response_rate_is_none_when_everything_is_too_new(session):
    add(session, date(2026, 10, 30), Stage.screen)

    result = stats(session, TODAY)

    assert result.response_rate is None and result.old_enough == 0
    assert result.interview_rate is None
    assert result.total == 1


def test_interview_rate_counts_interview_onsite_or_offer_over_old_enough(session):
    add(session, OLD, Stage.screen, Stage.interview, Stage.rejected)
    add(session, OLD, Stage.onsite)
    add(session, OLD, Stage.offer)
    add(session, OLD, Stage.screen)
    add(session, date(2026, 10, 30), Stage.interview)  # 1 day old: left out, even with an interview

    result = stats(session, TODAY)

    assert (result.interviewed, result.old_enough, result.total) == (3, 4, 5)
    assert result.interview_rate == pytest.approx(0.75)


def test_days_since_last_application(session):
    add(session, OLD)
    add(session, date(2026, 10, 24))

    assert stats(session, TODAY).days_since_last_application == 7


def test_applied_today_is_zero_days_and_future_dates_never_go_negative(session):
    add(session, date(2026, 11, 2))

    assert stats(session, TODAY).days_since_last_application == 0
