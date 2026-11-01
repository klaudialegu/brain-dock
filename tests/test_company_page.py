import html
from datetime import date

from sqlalchemy import event

from brain_dock.core.security import CONTENT_SECURITY_POLICY
from brain_dock.modules.job_search.models import (
    RoleTrack,
    Stage,
    create_application,
    get_or_create_company,
    record_stage,
)
from brain_dock.modules.job_search.queries import company_detail

from .conftest import SECRET


def add(session, company="Acme Analytics", role="Solutions Engineer", applied=date(2026, 10, 1)):
    application = create_application(
        session, get_or_create_company(session, company), role, RoleTrack.fde, applied
    )
    session.commit()
    return application


def count_queries(session, run):
    """Run `run()` and return how many SQL statements it sent to the database."""
    statements = []

    def seen(conn, cursor, statement, *args):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", seen)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    return len(statements)


# --- The query ---------------------------------------------------------------------------


def test_company_detail_lists_its_applications_newest_first(session):
    older = add(session, role="Support Engineer", applied=date(2026, 9, 1))
    newer = add(session, role="Solutions Engineer", applied=date(2026, 10, 1))
    add(session, company="Other Co")

    detail = company_detail(session, older.company_id)

    assert detail.name == "Acme Analytics"
    assert [a.id for a in detail.applications] == [newer.id, older.id]


def test_company_detail_unknown_id_is_none(session):
    add(session)

    assert company_detail(session, 999) is None


def test_timeline_orders_same_day_events_by_recording_order(session):
    application = add(session, applied=date(2026, 10, 1))
    # Recorded in an order that is neither the pipeline order, nor alphabetical, nor reversed,
    # so only "date, then id" gives this result.
    for stage in (Stage.onsite, Stage.screen, Stage.interview):
        record_stage(session, application, stage, date(2026, 10, 5))
    session.commit()

    (app,) = company_detail(session, application.company_id).applications

    assert [e.stage for e in app.events] == [
        Stage.applied,
        Stage.onsite,
        Stage.screen,
        Stage.interview,
    ]


def test_company_detail_loads_events_eagerly(session):
    company_id = add(session, role="Role 1").company_id
    for n in (2, 3, 4):
        add(session, role=f"Role {n}")
    session.expire_all()  # nothing cached: every relationship must come from the database

    # One query for the company, one for its applications, one for all their events,
    # however many applications there are. Lazy loading would be 2 + one per application.
    detail = None

    def load():
        nonlocal detail
        detail = company_detail(session, company_id)

    assert count_queries(session, load) == 3
    assert len(detail.applications) == 4  # it really loaded them all


# --- The page ----------------------------------------------------------------------------


def test_company_page_shows_applications_and_timeline(client, session):
    add(session, company="Other Co", role="Other Role")  # first, so the page isn't company 1
    application = add(session, role="Solutions Engineer")
    record_stage(session, application, Stage.screen, date(2026, 10, 8), note="Recruiter call")
    session.commit()

    response = client.get(f"/companies/{application.company_id}")

    assert response.status_code == 200
    assert "<h1>Acme Analytics</h1>" in response.text
    assert "Solutions Engineer" in response.text
    assert "2026-10-08" in response.text and "Recruiter call" in response.text
    assert f'href="/applications/{application.id}/edit"' in response.text
    assert "Other Role" not in response.text  # only this company's applications
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_applications_list_links_to_company_page(client, session):
    application = add(session)

    response = client.get("/applications")

    assert f'<a href="/companies/{application.company_id}">Acme Analytics</a>' in response.text


def test_company_name_is_escaped_in_title_and_heading(client, session):
    name = '<script>alert("x")</script> & Co'
    application = add(session, company=name)

    response = client.get(f"/companies/{application.company_id}")

    escaped = html.escape(name, quote=False)
    assert "<script>alert" not in response.text
    assert f"<title>{escaped} · Career Radar · Brain Dock</title>" in response.text.replace(
        "&#34;", '"'
    )
    assert f"<h1>{escaped}</h1>" in response.text.replace("&#34;", '"')


def test_unknown_company_is_an_html_404(client, session):
    add(session)

    response = client.get("/companies/999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Page not found</h1>" in response.text


def test_non_integer_company_id_is_an_html_error_page_not_json(client):
    response = client.get(f"/companies/{SECRET}")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>That request didn't make sense</h1>" in html.unescape(response.text)
    assert SECRET not in response.text
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
