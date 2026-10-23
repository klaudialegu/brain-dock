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


# --- Each module turned off in turn ------------------------------------------------------


MODULES = registry.installed()


def seed_job_search(engine):
    from brain_dock.modules.job_search.importer import DEMO_JSON, load_applications, rebuild_db

    rebuild_db(engine, load_applications(DEMO_JSON), locked=False)
    return "Acme Analytics"  # a value the module's home page shows


# Fake data for each module, so "disabling keeps the data" checks real rows.
SEEDERS = {"job_search": seed_job_search}


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
        responses = [home] + [client.get(path) for path in m.paths]
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
