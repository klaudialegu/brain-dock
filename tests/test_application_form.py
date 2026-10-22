import logging
import re
from datetime import date

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlmodel import func, select

from brain_dock.main import app, get_session
from brain_dock.models import Application, Company, Stage, StageEvent
from brain_dock.security import CSRF_COOKIE, verify_csrf

from .conftest import BASE_URL

SECRET = "SECRET-VALUE-42"
VALID = {
    "company": "Acme Analytics",
    "role_title": "Forward Deployed Engineer",
    "role_track": "fde",
    "applied_on": "2026-10-21",
    "link": "https://example.com/jobs/1",
    "notes": "Fake notes",
    "follow_up_on": "2026-10-28",
}


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, base_url=BASE_URL)
    app.dependency_overrides.clear()


def form_token(client):
    response = client.get("/applications/new")
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def post(client, data, *, token=None, headers=None):
    token = form_token(client) if token is None else token
    return client.post(
        "/applications",
        data={**data, "csrf_token": token},
        headers={"Origin": BASE_URL} if headers is None else headers,
        follow_redirects=False,
    )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


# --- Adding an application ---------------------------------------------------


def test_valid_form_adds_the_application_and_redirects(client, session):
    response = post(client, VALID)

    assert response.status_code == 303
    assert response.headers["location"] == "/applications"
    assert count(session, Application) == 1  # the post really wrote something
    app_ = session.exec(select(Application)).one()
    assert (app_.company.name, app_.role_title, app_.role_track) == (
        "Acme Analytics",
        "Forward Deployed Engineer",
        "fde",
    )
    assert (app_.applied_on, app_.follow_up_on) == (date(2026, 10, 21), date(2026, 10, 28))
    assert app_.current_stage == Stage.applied
    assert [(e.stage, e.happened_on) for e in app_.events] == [(Stage.applied, date(2026, 10, 21))]
    assert "Forward Deployed Engineer" in client.get("/applications").text


def test_blank_optional_fields_are_saved_as_empty(client, session):
    post(client, VALID | {"link": "", "notes": "  ", "follow_up_on": ""})

    app_ = session.exec(select(Application)).one()
    assert (app_.link, app_.notes, app_.follow_up_on) == (None, None, None)


def test_company_is_matched_ignoring_case_and_spaces(client, session):
    post(client, VALID)
    post(client, VALID | {"company": "  acme ANALYTICS ", "role_title": "Support Lead"})

    assert count(session, Application) == 2
    assert list(session.exec(select(Company.name))) == ["Acme Analytics"]


def test_new_company_name_is_stored_trimmed(client, session):
    post(client, VALID | {"company": "  Globex Systems  "})

    assert list(session.exec(select(Company.name))) == ["Globex Systems"]


# --- Same validation rules as the importer -----------------------------------


@pytest.mark.parametrize(
    ("change", "field", "message"),
    [
        ({"role_track": "astronaut"}, "role_track", "Track: Input should be"),
        ({"link": "javascript:alert(1)"}, "link", "Job link: must be an http:// or https:// URL"),
        ({"link": "example.com"}, "link", "Job link: must be an http:// or https:// URL"),
        ({"company": "   "}, "company", "Company: String should have at least 1 character"),
        ({"role_title": ""}, "role_title", "Role: String should have at least 1 character"),
        ({"applied_on": "not-a-date"}, "applied_on", "Applied on: Input should be a valid date"),
        ({"follow_up_on": "2026-13-40"}, "follow_up_on", "Follow-up: Input should be a valid date"),
    ],
)
def test_invalid_input_is_rejected_with_a_field_message(client, session, change, field, message):
    response = post(client, VALID | change)

    assert response.status_code == 400
    assert message in response.text
    assert f'id="{field}-error"' in response.text
    assert count(session, Application) == 0


def test_tampered_extra_field_is_rejected_without_naming_it(client, session):
    response = post(client, VALID | {SECRET: "x"})

    assert response.status_code == 400
    assert "The form contained something unexpected" in response.text
    assert SECRET not in response.text
    assert count(session, Application) == 0


def test_rejected_form_keeps_what_was_typed(client):
    response = post(client, VALID | {"link": "javascript:alert(1)", "notes": "Keep me"})

    assert "Keep me" in response.text
    assert 'value="Acme Analytics"' in response.text


# --- Typed values never reach logs or error messages ------------------------


def test_typed_values_never_appear_in_logs(client, caplog):
    marked = {k: f"{SECRET}-{k}" for k in VALID} | {"role_track": "fde"}
    caplog.set_level(logging.DEBUG)

    post(client, marked)  # invalid: dates and link are nonsense
    post(client, VALID | {"notes": SECRET, "company": f"{SECRET} Co"})  # valid

    assert caplog.records  # the capture works: something was logged
    assert all(SECRET not in r.getMessage() for r in caplog.records)
    assert SECRET not in caplog.text


def test_error_messages_never_contain_typed_values(client):
    marked = VALID | {"applied_on": SECRET, "link": f"javascript:{SECRET}", "role_track": SECRET}

    html = post(client, marked).text
    messages = re.findall(r'<span class="field-error"[^>]*>([^<]*)</span>', html)

    assert len(messages) == 3
    assert all(SECRET not in m for m in messages)


def test_request_validation_reply_never_includes_the_input():
    import asyncio

    from fastapi.exceptions import RequestValidationError

    from brain_dock.main import invalid_request

    exc = RequestValidationError(
        [{"type": "int_parsing", "loc": ("path", "id"), "msg": "bad", "input": SECRET}]
    )
    response = asyncio.run(invalid_request(None, exc))

    assert response.status_code == 422
    assert response.body == b"Invalid request"
    assert app.exception_handlers[type(exc)] is invalid_request  # it's the registered handler


# --- CSRF -------------------------------------------------------------------


def test_form_sets_a_strict_http_only_cookie(client):
    response = client.get("/applications/new")

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{CSRF_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie


def test_two_tabs_share_one_token(client, session):
    first, second = form_token(client), form_token(client)

    assert first == second
    assert post(client, VALID, token=first).status_code == 303
    assert post(client, VALID | {"role_title": "Second tab"}, token=second).status_code == 303
    assert count(session, Application) == 2


def test_malformed_cookie_is_replaced(client):
    client.cookies.set(CSRF_COOKIE, "short")

    response = client.get("/applications/new")

    assert "set-cookie" in response.headers
    assert response.headers["set-cookie"] != f"{CSRF_COOKIE}=short"


def test_missing_token_is_refused(client, session):
    form_token(client)
    response = client.post(
        "/applications", data=VALID, headers={"Origin": BASE_URL}, follow_redirects=False
    )

    assert response.status_code == 403
    assert count(session, Application) == 0


def test_wrong_token_is_refused(client, session):
    form_token(client)

    assert post(client, VALID, token="x" * 43).status_code == 403
    assert count(session, Application) == 0


def test_missing_cookie_is_refused(client, session):
    token = form_token(client)
    client.cookies.clear()

    assert post(client, VALID, token=token).status_code == 403
    assert count(session, Application) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "http://127.0.0.1:9999"},  # right host, wrong port
        {"Origin": "null"},
        {"Origin": BASE_URL, "Sec-Fetch-Site": "cross-site"},
        {"Referer": "https://evil.example/page"},
        {},  # neither Origin nor Referer
    ],
)
def test_foreign_or_missing_origin_is_refused(client, session, headers):
    assert post(client, VALID, headers=headers).status_code == 403
    assert count(session, Application) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://127.0.0.1:8000"},
        {"Origin": "http://localhost:8000"},
        {"Referer": "http://localhost:8000/applications/new"},  # no Origin, valid Referer
        {"Origin": BASE_URL, "Sec-Fetch-Site": "same-origin"},
    ],
)
def test_own_origins_are_accepted(client, session, headers):
    assert post(client, VALID, headers=headers).status_code == 303
    assert count(session, Application) == 1


def test_unknown_host_is_refused(session):
    app.dependency_overrides[get_session] = lambda: session
    rebinding = TestClient(app, base_url="http://evil.example:8000")

    assert rebinding.get("/applications").status_code == 400
    assert rebinding.post("/applications", data=VALID).status_code == 400
    app.dependency_overrides.clear()


def test_every_post_route_checks_csrf():
    post_routes = [r for r in app.routes if isinstance(r, APIRoute) and "POST" in r.methods]

    assert post_routes  # the check covers real routes
    for route in post_routes:
        assert verify_csrf in [d.call for d in route.dependant.dependencies], route.path


# --- Pages -------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/applications", "/applications/new"])
def test_pages_with_personal_data_are_not_cached(client, path):
    assert client.get(path).headers["cache-control"] == "no-store"


def test_list_page_links_to_the_form(client):
    assert (
        '<a class="button" href="/applications/new">Add application</a>'
        in client.get("/applications").text
    )


def test_stage_events_written_by_the_form(client, session):
    post(client, VALID)

    assert count(session, StageEvent) == 1
