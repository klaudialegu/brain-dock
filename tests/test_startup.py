import pytest
from fastapi.testclient import TestClient

from brain_dock.db import get_engine, migrate
from brain_dock.main import DatabaseNotReadyError, app

from .conftest import BASE_URL
from .test_migrations import legacy_db

# --- App startup -------------------------------------------------------------
# The autouse fixture in conftest.py points db.DB_PATH at a temp file.


def test_startup_refuses_a_missing_database():
    with pytest.raises(DatabaseNotReadyError, match="uv run python -m brain_dock.db"):
        with TestClient(app, base_url=BASE_URL):
            pass


def test_startup_refuses_an_unmigrated_database():
    legacy = get_engine()
    legacy_db(legacy)
    legacy.dispose()

    with pytest.raises(DatabaseNotReadyError, match="needs migrating"):
        with TestClient(app, base_url=BASE_URL):
            pass


def test_startup_succeeds_after_migrating():
    ready = get_engine()
    migrate(ready)
    ready.dispose()

    with TestClient(app, base_url=BASE_URL) as client:
        assert client.get("/applications").status_code == 200
