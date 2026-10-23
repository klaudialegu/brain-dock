import html
import logging
import re
from datetime import date

import pytest
from sqlmodel import func, select

from brain_dock.modules.job_search.models import (
    Application,
    Company,
    RoleTrack,
    Stage,
    create_application,
    get_or_create_company,
    record_stage,
)

from .conftest import BASE_URL, SECRET


def add(session, company="Acme Analytics", role="Solutions Engineer", applied=date(2026, 10, 1)):
    application = create_application(
        session, get_or_create_company(session, company), role, RoleTrack.fde, applied
    )
    session.commit()
    return application


def fields(application, **changes):
    values = {
        "company": application.company.name,
        "role_title": application.role_title,
        "role_track": application.role_track.value,
        "applied_on": application.applied_on.isoformat(),
        "link": application.link or "",
        "notes": application.notes or "",
        "follow_up_on": application.follow_up_on.isoformat() if application.follow_up_on else "",
    }
    return values | changes


def token(client, application_id):
    html = client.get(f"/applications/{application_id}/edit").text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def save(client, application, data, headers=None):
    return client.post(
        f"/applications/{application.id}",
        data={**data, "csrf_token": token(client, application.id)},
        headers={"Origin": BASE_URL} if headers is None else headers,
        follow_redirects=False,
    )


def companies(session):
    return sorted(session.exec(select(Company.name)))


# --- Edit page ---------------------------------------------------------------


def test_edit_page_shows_fields_and_history(client, session):
    application = add(session)
    record_stage(session, application, Stage.screen, date(2026, 10, 5), note="Recruiter call")
    session.commit()

    response = client.get(f"/applications/{application.id}/edit")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'value="Acme Analytics"' in response.text
    assert 'action="/applications/' + str(application.id) + '"' in response.text
    assert "Recruiter call" in response.text
    assert '<span class="stage stage-screen">Screen</span>' in response.text


def test_list_rows_link_to_their_edit_page(client, session):
    application = add(session)

    assert f'href="/applications/{application.id}/edit"' in client.get("/applications").text


def test_unknown_application_is_404(client):
    response = client.get("/applications/999/edit")

    assert response.status_code == 404
    assert "999" not in response.text


def test_non_numeric_id_is_rejected_without_echo(client):
    response = client.get(f"/applications/{SECRET}/edit")

    assert response.status_code == 422
    assert "That request didn't make sense" in html.unescape(response.text)
    assert SECRET not in response.text


# --- Saving edits ------------------------------------------------------------


def test_edit_saves_every_field(client, session):
    application = add(session)

    response = save(
        client,
        application,
        fields(
            application,
            role_title="Forward Deployed Engineer",
            role_track="support",
            applied_on="2026-09-30",
            link="https://example.com/jobs/9",
            notes="Updated notes",
            follow_up_on="2026-10-10",
        ),
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/applications"
    session.refresh(application)
    assert (application.role_title, application.role_track) == (
        "Forward Deployed Engineer",
        "support",
    )
    assert application.applied_on == date(2026, 9, 30)
    assert (application.link, application.notes) == ("https://example.com/jobs/9", "Updated notes")
    assert application.follow_up_on == date(2026, 10, 10)


def test_clearing_optional_fields(client, session):
    application = add(session)
    application.link, application.notes = "https://example.com/x", "Old notes"
    session.commit()

    save(client, application, fields(application, link="", notes="", follow_up_on=""))

    session.refresh(application)
    assert (application.link, application.notes, application.follow_up_on) == (None, None, None)


def test_creation_event_moves_with_applied_on(client, session):
    application = add(session)

    save(client, application, fields(application, applied_on="2026-09-25"))

    session.refresh(application)
    assert [(e.stage, e.happened_on) for e in application.events] == [
        (Stage.applied, date(2026, 9, 25))
    ]


def test_applied_on_cannot_move_after_a_later_stage(client, session):
    application = add(session)
    record_stage(session, application, Stage.screen, date(2026, 10, 5))
    session.commit()

    response = save(client, application, fields(application, applied_on="2026-10-06"))

    assert response.status_code == 400
    assert "Applied on: must be on or before the first recorded stage" in response.text
    session.refresh(application)
    assert application.applied_on == date(2026, 10, 1)
    assert sorted(e.happened_on for e in application.events) == [
        date(2026, 10, 1),
        date(2026, 10, 5),
    ]


def test_applied_on_can_move_up_to_the_first_later_stage(client, session):
    application = add(session)
    record_stage(session, application, Stage.screen, date(2026, 10, 5))
    session.commit()

    assert (
        save(client, application, fields(application, applied_on="2026-10-05")).status_code == 303
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"link": "javascript:alert(1)"}, "Job link: must be an http:// or https:// URL"),
        ({"role_track": "astronaut"}, "Track: Input should be"),
        ({"company": " "}, "Company: String should have at least 1 character"),
    ],
)
def test_edit_uses_the_same_validation(client, session, change, message):
    application = add(session)

    response = save(client, application, fields(application, **change))

    assert response.status_code == 400
    assert message in response.text
    session.refresh(application)
    assert application.role_track == RoleTrack.fde and application.link is None


# --- Company renames ---------------------------------------------------------


def test_renaming_the_only_application_removes_the_old_company(client, session):
    application = add(session, company="Acme Analytics")

    save(client, application, fields(application, company="Globex Systems"))

    assert companies(session) == ["Globex Systems"]


def test_renaming_one_of_two_keeps_the_old_company(client, session):
    first = add(session, company="Acme Analytics", role="First")
    add(session, company="Acme Analytics", role="Second")

    save(client, first, fields(first, company="Globex Systems"))

    assert companies(session) == ["Acme Analytics", "Globex Systems"]


def test_renaming_to_an_existing_company_merges_into_it(client, session):
    add(session, company="Globex Systems", role="Existing")
    moving = add(session, company="Acme Analytics", role="Moving")

    save(client, moving, fields(moving, company="  globex SYSTEMS "))

    assert companies(session) == ["Globex Systems"]
    session.refresh(moving)
    assert moving.company.name == "Globex Systems"


def test_same_company_with_new_spelling_updates_its_name(client, session):
    application = add(session, company="acme analytics")

    save(client, application, fields(application, company="Acme Analytics"))

    assert companies(session) == ["Acme Analytics"]


# --- Security ----------------------------------------------------------------


def test_edit_requires_csrf(client, session):
    application = add(session)

    response = client.post(
        f"/applications/{application.id}",
        data=fields(application, role_title="Changed"),
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )

    assert response.status_code == 403
    session.refresh(application)
    assert application.role_title == "Solutions Engineer"


def test_edit_refuses_a_foreign_origin(client, session):
    application = add(session)

    response = save(
        client,
        application,
        fields(application, role_title="Changed"),
        {"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_editing_an_unknown_application_is_404(client, session):
    application = add(session)
    data = {**fields(application), "csrf_token": token(client, application.id)}

    response = client.post(
        "/applications/999", data=data, headers={"Origin": BASE_URL}, follow_redirects=False
    )

    assert response.status_code == 404


def test_edit_never_logs_typed_values(client, session, caplog):
    application = add(session)
    caplog.set_level(logging.DEBUG)

    save(client, application, fields(application, notes=SECRET, link=f"javascript:{SECRET}"))
    save(client, application, fields(application, notes=SECRET))

    assert caplog.records
    assert SECRET not in caplog.text
    assert session.scalar(select(func.count()).select_from(Application)) == 1


# --- Recording a stage -------------------------------------------------------


def record(client, application, data, headers=None):
    return client.post(
        f"/applications/{application.id}/stages",
        data={**data, "csrf_token": token(client, application.id)},
        headers={"Origin": BASE_URL} if headers is None else headers,
        follow_redirects=False,
    )


def test_record_stage_form_offers_every_stage_but_applied(client, session):
    application = add(session)

    html = client.get(f"/applications/{application.id}/edit").text
    stage_select = html[
        html.index('name="stage"') : html.index("</select>", html.index('name="stage"'))
    ]

    assert 'value="applied"' not in stage_select
    for stage in ["screen", "interview", "onsite", "offer", "rejected", "ghosted", "withdrawn"]:
        assert f'value="{stage}"' in stage_select


def test_recording_a_stage_updates_current_stage_and_history(client, session):
    application = add(session)

    response = record(
        client, application, {"stage": "screen", "happened_on": "2026-10-05", "note": " Call "}
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/applications/{application.id}/edit"
    session.refresh(application)
    assert application.current_stage == Stage.screen
    assert [(e.stage, e.note) for e in application.events][-1] == (Stage.screen, "Call")


def test_blank_note_is_saved_as_empty(client, session):
    application = add(session)

    record(client, application, {"stage": "screen", "happened_on": "2026-10-05", "note": "  "})

    session.refresh(application)
    assert application.events[-1].note is None


def test_backfilled_stage_does_not_move_current_stage_back(client, session):
    application = add(session)
    record(client, application, {"stage": "interview", "happened_on": "2026-10-10"})

    record(client, application, {"stage": "screen", "happened_on": "2026-10-05"})

    session.refresh(application)
    assert application.current_stage == Stage.interview
    assert len(application.events) == 3


def test_stage_before_applied_on_is_refused(client, session):
    application = add(session)

    response = record(client, application, {"stage": "screen", "happened_on": "2026-09-30"})

    assert response.status_code == 400
    assert "Date: must be on or after the applied date" in response.text
    session.refresh(application)
    assert len(application.events) == 1 and application.current_stage == Stage.applied


def test_stage_on_the_applied_date_is_allowed(client, session):
    application = add(session)

    assert (
        record(client, application, {"stage": "rejected", "happened_on": "2026-10-01"}).status_code
        == 303
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"stage": "applied", "happened_on": "2026-10-05"}, "Stage: "),
        ({"stage": SECRET, "happened_on": "2026-10-05"}, "Stage: Input should be"),
        ({"stage": "screen", "happened_on": SECRET}, "Date: Input should be a valid date"),
    ],
)
def test_invalid_stage_input_is_refused_without_echo(client, session, data, message):
    application = add(session)

    response = record(client, application, data)

    assert response.status_code == 400
    assert message in response.text
    errors = re.findall(r'<span class="field-error"[^>]*>([^<]*)</span>', response.text)
    assert errors and all(SECRET not in e for e in errors)
    session.refresh(application)
    assert len(application.events) == 1


def test_record_stage_requires_csrf(client, session):
    application = add(session)

    response = client.post(
        f"/applications/{application.id}/stages",
        data={"stage": "screen", "happened_on": "2026-10-05"},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )

    assert response.status_code == 403
    session.refresh(application)
    assert len(application.events) == 1


def test_record_stage_refuses_a_foreign_origin(client, session):
    application = add(session)

    response = record(
        client,
        application,
        {"stage": "screen", "happened_on": "2026-10-05"},
        {"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_recording_on_an_unknown_application_is_404(client, session):
    application = add(session)
    data = {
        "stage": "screen",
        "happened_on": "2026-10-05",
        "csrf_token": token(client, application.id),
    }

    response = client.post(
        "/applications/999/stages", data=data, headers={"Origin": BASE_URL}, follow_redirects=False
    )

    assert response.status_code == 404


def test_record_stage_never_logs_typed_values(client, session, caplog):
    application = add(session)
    caplog.set_level(logging.DEBUG)

    record(client, application, {"stage": "screen", "happened_on": "2026-10-05", "note": SECRET})
    record(client, application, {"stage": SECRET, "happened_on": "2026-10-05", "note": SECRET})

    assert caplog.records
    assert SECRET not in caplog.text
    session.refresh(application)
    assert len(application.events) == 2
