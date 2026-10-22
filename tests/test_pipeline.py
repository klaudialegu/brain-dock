from datetime import date

from brain_dock.models import (
    RoleTrack,
    Stage,
    create_application,
    get_or_create_company,
    record_stage,
)
from brain_dock.queries import PipelineLink, pipeline_links

A, S, INTV, ONS, OFFER = Stage.applied, Stage.screen, Stage.interview, Stage.onsite, Stage.offer
REJ, GHOST, WD = Stage.rejected, Stage.ghosted, Stage.withdrawn


def app_with(session, *stages, role="Role"):
    """An application that went through the given stages, one day apart."""
    application = create_application(
        session,
        get_or_create_company(session, "Acme Analytics"),
        role,
        RoleTrack.fde,
        date(2026, 10, 1),
    )
    for day, stage in enumerate(stages, start=2):
        record_stage(session, application, stage, date(2026, 10, day))
    session.commit()
    return application


def links(session):
    return {(link.source, link.target): link.count for link in pipeline_links(session)}


def test_no_applications_no_links(session):
    assert pipeline_links(session) == []


def test_application_still_at_applied_has_no_links(session):
    app_with(session)

    assert pipeline_links(session) == []


def test_simple_path(session):
    app_with(session, S, INTV, REJ)

    assert links(session) == {(A, S): 1, (S, INTV): 1, (INTV, REJ): 1}


def test_paths_add_up_and_branch(session):
    app_with(session, S, INTV, ONS, OFFER)
    app_with(session, S, REJ)
    app_with(session, GHOST)
    app_with(session, S)  # still active at screen

    assert links(session) == {
        (A, S): 3,
        (S, INTV): 1,
        (INTV, ONS): 1,
        (ONS, OFFER): 1,
        (S, REJ): 1,
        (A, GHOST): 1,
    }


def test_repeated_and_backwards_steps_are_left_out(session):
    # Two interview rounds, and a screen recorded after the interview.
    app_with(session, S, INTV, INTV, S, ONS)

    assert links(session) == {(A, S): 1, (S, INTV): 1, (INTV, ONS): 1}


def test_skipped_stages_link_directly(session):
    app_with(session, INTV, OFFER)  # straight to interview

    assert links(session) == {(A, INTV): 1, (INTV, OFFER): 1}


def test_offer_then_withdrawn_ends_at_withdrawn(session):
    app_with(session, S, OFFER, WD)

    assert links(session) == {(A, S): 1, (S, OFFER): 1, (OFFER, WD): 1}


def test_links_are_ordered_left_to_right(session):
    app_with(session, GHOST)
    app_with(session, S, INTV)

    assert [(link.source, link.target) for link in pipeline_links(session)] == [
        (A, S),
        (A, GHOST),
        (S, INTV),
    ]
    assert all(isinstance(link, PipelineLink) for link in pipeline_links(session))


def test_every_path_moves_forward_only(session):
    from brain_dock.queries import pipeline_path
    from brain_dock.stages import stage_order

    application = app_with(session, INTV, S, ONS, INTV, REJ, S)
    path = pipeline_path(application)

    assert [stage_order(s) for s in path] == sorted({stage_order(s) for s in path})
