"""ADR 0007: the core runs with modules turned off, and turning one off never touches its data."""

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from brain_dock import registry
from brain_dock.core import db
from brain_dock.core.app import create_app
from brain_dock.core.db import get_engine, migrate
from brain_dock.core.security import CONTENT_SECURITY_POLICY

from .conftest import BASE_URL


def test_core_runs_with_no_modules():
    ready = get_engine()  # the temp stand-in for data/brain_dock.db (conftest)
    migrate(ready)
    ready.dispose()

    with TestClient(create_app([]), base_url=BASE_URL) as client:
        home = client.get("/")
        gone = client.get("/applications")

    assert home.status_code == 200
    assert "No modules are enabled" in home.text
    assert '<nav aria-label="Main">' not in home.text  # no module, no nav
    assert gone.status_code == 404 and "Page not found" in gone.text
    assert 'href="/"' in gone.text  # the way back leads to the core, not a missing module
    for response in (home, gone):
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_home_without_modules_shows_tagline():
    ready = get_engine()
    migrate(ready)
    ready.dispose()

    with TestClient(create_app([]), base_url=BASE_URL) as client:
        home = client.get("/")

    assert "A modular personal daily-efficiency assistant." in home.text


# --- Each module turned off in turn ------------------------------------------------------


MODULES = registry.installed()


def seed_job_search(engine):
    from brain_dock.modules.job_search.importer import DEMO_JSON, load_applications, rebuild_db

    rebuild_db(engine, load_applications(DEMO_JSON), locked=False)
    return "Acme Analytics"  # a value the module's home page shows


def seed_inbox(engine):
    from datetime import UTC, datetime

    from sqlmodel import Session

    from brain_dock.modules.inbox.models import InboxEmail, InboxRole, InboxRoleSource

    now = datetime.now(UTC)
    with Session(engine) as session:
        mail = InboxEmail(key="e" * 64, received_at=now, status="parsed", role_count=1)
        role = InboxRole(
            item_key="r" * 64,
            company="Example Corp",
            title="Senior Forward Deployed Engineer",
            location="Remote",
            company_key="example corp",
            title_key="senior forward deployed engineer",
            location_key="remote",
            link_key="https://jobs.example.com/view/1",
            location_kind="remote",
            status="suggested",
            created_at=now,
        )
        session.add_all([mail, role])
        session.flush()
        session.add(InboxRoleSource(role_id=role.id, email_id=mail.id))
        session.commit()
    return "Suggested: 1"  # the status page shows counts only


# Fake data for each module, so "disabling keeps the data" checks real rows.
SEEDERS = {"job_search": seed_job_search, "inbox": seed_inbox}

# Pages with an id in the path: the manifest only lists path prefixes, so these are checked
# by hand. Each must answer 200 on the seeded data with the module on (see below).
PROBES = {"job_search": ("/companies/1",)}


def others(m):
    return [x for x in MODULES if x.name != m.name]


def rows(engine, tables):
    with engine.connect() as connection:
        return {
            t: sorted(map(tuple, connection.execute(text(f"SELECT * FROM {t}")))) for t in tables
        }


def seeded_database(m):
    # A new module needs a seeder here, or the data check below would have nothing to check.
    assert m.name in SEEDERS, f"add fake data for {m.name} to SEEDERS"
    engine = get_engine()  # the temp stand-in for data/brain_dock.db (conftest)
    migrate(engine)
    shown = SEEDERS[m.name](engine)
    return engine, shown


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_core_runs_with_module_disabled(m):
    engine, _ = seeded_database(m)
    engine.dispose()

    with TestClient(create_app(others(m)), base_url=BASE_URL) as client:
        home = client.get("/")  # follows the redirect, if another module is the home
        responses = [home] + [client.get(p) for p in m.paths + PROBES.get(m.name, ())]
        posted = client.post(m.home, data={})
        static = None
        if m.static is not None:
            first = sorted(p.name for p in m.static.iterdir())[0]
            static = client.get(f"/static/modules/{m.name}/{first}")

    assert home.status_code == 200
    for entry in m.nav:
        assert f">{entry.label}</a>" not in home.text, "the disabled module's nav is gone"
    for response in responses[1:]:
        assert response.status_code == 404 and "Page not found" in response.text
    assert posted.status_code == 404  # its forms are gone too, not just its pages
    assert static is None or static.status_code == 404
    for response in responses:
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_disabling_keeps_the_data(m):
    engine, shown = seeded_database(m)
    before = rows(engine, m.tables)
    engine.dispose()
    checksum = hashlib.sha256(db.DB_PATH.read_bytes()).hexdigest()

    assert any(before.values())  # there really is data to keep
    with TestClient(create_app(others(m)), base_url=BASE_URL) as client:
        client.get("/")
        for path in m.paths:
            client.get(path)

    engine = get_engine()
    assert rows(engine, m.tables) == before
    engine.dispose()
    assert hashlib.sha256(db.DB_PATH.read_bytes()).hexdigest() == checksum  # not even touched

    # Turned back on, the same data is there.
    with TestClient(create_app(MODULES), base_url=BASE_URL) as client:
        assert shown in client.get(m.home).text
        for path in PROBES.get(m.name, ()):
            assert client.get(path).status_code == 200, path  # so its 404 when off means off
