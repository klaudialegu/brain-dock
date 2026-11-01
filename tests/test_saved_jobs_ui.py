"""Saved jobs UI (PR 0b, ADR 0009): save a job I'm considering, see it in its own section,
mark it applied; the inbox links accepted roles to a prefilled save form (ADR 0011)."""

import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from brain_dock import registry
from brain_dock.core.agents.approvals import Approvals
from brain_dock.core.agents.audit import AuditLog
from brain_dock.core.app import create_app
from brain_dock.core.db import get_engine
from brain_dock.modules.job_search.models import (
    Application,
    RoleTrack,
    create_application,
    get_or_create_company,
    mark_applied,
    save_interested,
)
from brain_dock.modules.job_search.queries import list_applications, stats

from .conftest import BASE_URL
from .inbox_support import INBOX, app_key, run_fixtures

SAVED_ON = date(2026, 10, 12)
ORIGIN = {"Origin": BASE_URL}


def apply(session, role="Applied Role", company="Acme Analytics"):
    application = create_application(
        session, get_or_create_company(session, company), role, RoleTrack.fde, date(2026, 10, 1)
    )
    session.commit()
    return application


def save(session, role="Saved Role", company="Acme Analytics", link=None):
    job = save_interested(
        session, get_or_create_company(session, company), role, RoleTrack.fde, SAVED_ON, link=link
    )
    session.commit()
    return job


def token(page: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def saved_section(page: str) -> str:
    start = page.index('id="saved-heading"')
    return page[start : page.index("</section>", start)]


def field_value(page: str, name: str) -> str | None:
    match = re.search(rf'name="{name}"[^>]*value="([^"]*)"', page)
    return match.group(1) if match else None


def test_list_shows_saved_jobs_in_their_own_section(client, session):
    apply(session)
    save(session, link="https://example.com/jobs/saved")

    page = client.get("/applications").text
    saved = saved_section(page)

    assert "Saved Role" in saved and 'href="https://example.com/jobs/saved"' in saved
    assert "2026-10-12" in saved and 'action="/applications/' in saved
    assert "Applied Role" not in saved
    assert "Saved Role" not in page[page.index("</section>") :]  # not in the applications table
    assert "1 application, newest first." in page
    assert stats(session, date(2026, 10, 31)).total == 1


def test_save_form_saves_a_job_as_interested(client, session):
    form = client.get("/applications/saved/new").text
    data = {
        "csrf_token": token(form),
        "company": "Globex Systems",
        "role_title": "Solutions Engineer",
        "role_track": "fde",
        "interested_on": "2026-10-12",
        "link": "",
        "notes": "",
        "follow_up_on": "",
    }

    response = client.post("/applications/saved", data=data, headers=ORIGIN, follow_redirects=False)

    assert response.status_code == 303 and response.headers["location"] == "/applications"
    job = session.exec(select(Application)).one()
    assert job.applied_on is None and job.company.name == "Globex Systems"
    assert [(e.stage, e.happened_on) for e in job.events] == [("interested", SAVED_ON)]
    assert list_applications(session) == []  # saved, not applied


def test_save_form_shows_errors_next_to_fields(client, session):
    form = client.get("/applications/saved/new").text
    data = {
        "csrf_token": token(form),
        "company": " ",
        "role_title": "Solutions Engineer",
        "role_track": "fde",
        "interested_on": "2026-10-12",
        "link": "javascript:alert(1)",
    }

    response = client.post("/applications/saved", data=data, headers=ORIGIN)

    assert response.status_code == 400
    assert "Company:" in response.text and "Job link: must be an http" in response.text
    assert session.exec(select(Application)).all() == []


def test_mark_applied_turns_a_saved_job_into_an_application(client, session):
    job = save(session)
    page = client.get("/applications").text

    response = client.post(
        f"/applications/{job.id}/applied",
        data={"csrf_token": token(page), "applied_on": "2026-10-20"},
        headers=ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 303
    session.refresh(job)
    assert job.applied_on == date(2026, 10, 20) and job.current_stage == "applied"
    assert [r.role_title for r in list_applications(session)] == ["Saved Role"]
    assert client.get(f"/applications/{job.id}/edit").status_code == 200
    assert 'id="saved-heading"' not in client.get("/applications").text


def test_mark_applied_refuses_an_earlier_date_or_a_second_time(client, session):
    job = save(session)
    applied = apply(session)
    csrf = token(client.get("/applications").text)

    def mark(job_id, day):
        return client.post(
            f"/applications/{job_id}/applied",
            data={"csrf_token": csrf, "applied_on": day},
            headers=ORIGIN,
            follow_redirects=False,
        )

    too_early = mark(job.id, "2026-10-11")
    assert too_early.status_code == 400
    assert "must be on or after the day it was saved" in saved_section(too_early.text)
    session.refresh(job)
    assert job.applied_on is None

    assert mark(job.id, "2026-10-12").status_code == 303  # the same day is fine
    assert mark(job.id, "2026-10-13").status_code == 404  # not a saved job any more
    assert mark(applied.id, "2026-10-13").status_code == 404  # never was one
    assert mark(9999, "2026-10-13").status_code == 404


def test_company_page_shows_saved_jobs_separately(client, session):
    applied = apply(session)
    save(session)
    later_applied = save(session, role="Saved Then Applied")
    mark_applied(session, later_applied, date(2026, 10, 20))
    session.commit()
    only_saved = save(session, role="Only Saved", company="Initech")

    page = client.get(f"/companies/{applied.company_id}").text
    alone = client.get(f"/companies/{only_saved.company_id}")

    assert "Saved Role" in saved_section(page)
    assert "Saved Role" not in page[: page.index('id="saved-heading"')]  # not a timeline
    assert "Saved Then Applied" not in saved_section(page)  # applied now: in the timeline
    assert "Saved Then Applied" in page
    assert "Mark applied" not in page  # the company page only lists them
    assert alone.status_code == 200 and "Only Saved" in saved_section(alone.text)


def test_save_form_prefills_only_safe_values_from_the_link(client):
    safe = client.get(
        "/applications/saved/new",
        params={
            "company": "Example Corp",
            "role_title": "Senior Forward Deployed Engineer",
            "link": "https://jobs.example.com/view/101",
            "notes": "should not prefill",
        },
    ).text
    unsafe = client.get(
        "/applications/saved/new",
        params={"company": "Example Corp", "link": "javascript:alert(1)"},
    ).text

    assert field_value(safe, "company") == "Example Corp"
    assert field_value(safe, "role_title") == "Senior Forward Deployed Engineer"
    assert field_value(safe, "link") == "https://jobs.example.com/view/101"
    assert "should not prefill" not in safe
    assert field_value(unsafe, "link") == "" and "javascript" not in unsafe  # left empty
    assert field_value(safe, "interested_on") == date.today().isoformat()


def test_inbox_links_accepted_roles_to_the_save_form(tmp_path):
    run_fixtures(tmp_path)
    engine = get_engine()
    with Session(engine) as session:
        from brain_dock.core.agents.run_tables import Approval

        first = session.exec(select(Approval).order_by(Approval.id)).first()
    Approvals(engine, AuditLog(engine, app_key()), [INBOX], lambda: tmp_path).approve(first.id)
    engine.dispose()

    with TestClient(create_app(registry.installed()), base_url=BASE_URL) as client:
        inbox = client.get("/inbox").text
        links = re.findall(r'href="(/applications/saved/new\?[^"]+)"', inbox)
        form = client.get(links[0].replace("&amp;", "&")).text
    with TestClient(create_app([INBOX]), base_url=BASE_URL) as alone:  # job search off
        without = alone.get("/inbox").text

    assert len(links) == 1  # one accepted role, one link
    query = parse_qs(urlsplit(links[0].replace("&amp;", "&")).query)
    assert set(query) == {"company", "role_title", "link"}
    assert field_value(form, "company") == query["company"][0]
    assert field_value(form, "link") == "https://jobs.example.com/view/101"
    assert 'id="accepted-heading"' in without and "/applications/saved/new" not in without
