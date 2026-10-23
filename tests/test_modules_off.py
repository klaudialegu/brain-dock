"""ADR 0007: the core runs with modules turned off, and turning one off never touches its data."""

from fastapi.testclient import TestClient

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
