import re
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from brain_dock.core import db
from brain_dock.core.db import get_engine, migrate
from brain_dock.main import app
from brain_dock.modules.job_search.models import (
    Application,
    Company,
    RoleTrack,
    Stage,
    create_application,
    record_stage,
)
from brain_dock.modules.job_search.queries import list_applications, safe_link

from .conftest import BASE_URL, REAL_DB_PATH


def add(session, company_name, role_title, applied_on, **kwargs):
    company = session.exec(select(Company).where(Company.name == company_name)).first()
    if company is None:
        company = Company(name=company_name)
        session.add(company)
    application = create_application(
        session, company, role_title, kwargs.pop("track", RoleTrack.fde), applied_on, **kwargs
    )
    session.commit()
    return application


def hrefs(html):
    return re.findall(r'href="([^"]*)"', html)


# --- safe_link ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["https://example.com/jobs/1", "http://example.com", "HTTPS://example.com/x"]
)
def test_safe_link_keeps_http_urls(url):
    assert safe_link(url) == url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://example.com/file",
        "//example.com/no-scheme",
        "https:no-host",
        "example.com",
    ],
)
def test_safe_link_drops_everything_else(url):
    assert safe_link(url) is None


# --- list_applications -------------------------------------------------------


def test_newest_first_then_most_recently_added(session):
    add(session, "Acme Analytics", "Older", date(2026, 9, 1))
    add(session, "Globex Systems", "Same day, added first", date(2026, 10, 1))
    add(session, "Initech", "Same day, added second", date(2026, 10, 1))

    assert [r.role_title for r in list_applications(session)] == [
        "Same day, added second",
        "Same day, added first",
        "Older",
    ]


def test_rows_carry_company_and_current_stage(session):
    app_ = add(session, "Acme Analytics", "Solutions Engineer", date(2026, 10, 1))
    record_stage(session, app_, Stage.screen, date(2026, 10, 5))
    session.commit()

    [row] = list_applications(session)

    assert (row.company, row.current_stage) == ("Acme Analytics", Stage.screen)


# --- The page ----------------------------------------------------------------


def test_empty_state_invites_adding_the_first_application(client):
    response = client.get("/applications")

    assert response.status_code == 200
    assert (
        'No applications yet. <a href="/applications/new">Add your first application</a>.'
        in response.text
    )


def test_page_lists_applications_with_details(client, session):
    add(
        session,
        "Acme Analytics",
        "Forward Deployed Engineer",
        date(2026, 10, 1),
        follow_up_on=date(2026, 10, 8),
    )
    add(session, "Globex Systems", "Support Lead", date(2026, 9, 1), track=RoleTrack.support)

    html = client.get("/applications").text

    assert "2 applications, newest first." in html
    assert html.index("Acme Analytics") < html.index("Globex Systems")
    for text in ["Forward Deployed Engineer", "FDE", "Support", "2026-10-01", "2026-10-08"]:
        assert text in html
    assert '<span class="stage stage-applied">Applied</span>' in html


def test_job_link_opens_safely_in_a_new_tab(client, session):
    add(session, "Acme Analytics", "Engineer", date(2026, 10, 1), link="https://example.com/jobs/1")

    html = client.get("/applications").text

    expected = (
        '<a href="https://example.com/jobs/1" target="_blank" rel="noopener noreferrer">'
        "Engineer</a>"
    )
    assert expected in html


def test_javascript_url_never_reaches_an_href(client, session):
    # Bypasses the importer on purpose: the page must be safe on its own.
    company = Company(name="Acme Analytics")
    session.add(company)
    session.add(
        Application(
            company=company,
            role_title="Sneaky Role",
            role_track=RoleTrack.other,
            applied_on=date(2026, 10, 1),
            link="javascript:alert(1)",
        )
    )
    session.commit()

    html = client.get("/applications").text

    assert "Sneaky Role" in html
    assert not any("javascript" in h.lower() for h in hrefs(html))
    assert "javascript:" not in html.lower()


def test_html_in_data_is_escaped(client, session):
    add(session, "<script>alert(1)</script>", "Engineer", date(2026, 10, 1))

    html = client.get("/applications").text

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


@pytest.mark.parametrize(
    ("path", "current"),
    [("/applications", "Career Radar"), ("/applications/new", "Add application")],
)
def test_nav_on_every_page_marks_the_current_one(client, path, current):
    html = client.get(path).text

    assert '<nav aria-label="Main">' in html
    assert f'aria-current="page">{current}</a>' in html


# --- Career Radar: the job search module's display name (ADR 0012) -----------


def test_applications_page_is_career_radar(client, session):
    add(session, "Acme", "Support Engineer", date(2026, 10, 1))

    html = client.get("/applications").text

    assert "<h1>Career Radar</h1>" in html
    assert "Market and skills views are planned." in html
    # The Applications heading sits after Pipeline and right above the table it names.
    pipeline = html.index('<h2 id="pipeline-heading">Pipeline</h2>')
    heading = html.index("<h2>Applications</h2>")
    table = html.index("application, newest first.")
    assert pipeline < heading < table


def test_applications_heading_shown_when_empty(client):
    html = client.get("/applications").text

    assert html.index("<h2>Applications</h2>") < html.index("No applications yet.")


@pytest.mark.parametrize(
    "path",
    [
        "/applications",
        "/applications/new",
        "/applications/saved/new",
        "/applications/{id}/edit",
        "/companies/{company_id}",
    ],
)
def test_module_pages_title_career_radar(client, session, path):
    application = add(session, "Acme", "Support Engineer", date(2026, 10, 1))

    html = client.get(path.format(id=application.id, company_id=application.company_id)).text

    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert title.endswith("Career Radar · Brain Dock"), title


# --- Startup never touches the real database ---------------------------------


def test_startup_never_opens_the_real_database(monkeypatch):
    existed_before = REAL_DB_PATH.exists()
    opened = []
    real_connect = sqlite3.dbapi2.connect

    def spy_connect(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)

    # SQLAlchemy opens SQLite files through sqlite3.dbapi2.connect.
    monkeypatch.setattr(sqlite3.dbapi2, "connect", spy_connect)
    monkeypatch.setattr(sqlite3, "connect", spy_connect)

    migrate(get_engine())  # the temp stand-in for data/brain_dock.db, via db.DB_PATH

    # Runs the real startup (lifespan: database checks) and a real page request.
    with TestClient(app, base_url=BASE_URL) as client:
        assert client.get("/applications").status_code == 200

    assert str(db.DB_PATH) in opened  # the spy works: the temp database was used
    assert str(REAL_DB_PATH) not in opened
    assert REAL_DB_PATH.exists() == existed_before
