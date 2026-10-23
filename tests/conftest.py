import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from brain_dock.core import db
from brain_dock.core.db import create_db, get_engine
from brain_dock.main import app, get_session
from brain_dock.modules.job_search import export

# The app only answers to its own host names (TrustedHostMiddleware), so test clients
# must use one of them instead of TestClient's default "testserver".
BASE_URL = "http://127.0.0.1:8000"


def all_templates():
    """Every template the app can render: the core's and every installed module's."""
    from brain_dock import registry
    from brain_dock.core.app import TEMPLATES_DIR

    folders = [TEMPLATES_DIR] + [m.templates for m in registry.installed()]
    return sorted(p for folder in folders for p in folder.rglob("*.html"))


# A distinctive value planted in input, so tests can prove it never shows up in
# error messages, logs or responses.
SECRET = "SECRET-VALUE-42"

# The real database, as it is before any test can patch it.
REAL_DB_PATH = db.DB_PATH


@pytest.fixture(autouse=True)
def never_use_the_real_database(tmp_path, monkeypatch):
    # Anything that falls back to the default database (like app startup)
    # gets a temp file instead of data/brain_dock.db.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "default.db")
    monkeypatch.setattr(export, "BACKUP_DIR", tmp_path / "backups")


@pytest.fixture
def session():
    # A fresh in-memory database per test. StaticPool keeps one connection open,
    # because an in-memory SQLite database disappears when its connection closes.
    engine = get_engine("sqlite://", poolclass=StaticPool)
    create_db(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(session):
    """A test client whose requests use the in-memory test database, never data/."""
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, base_url=BASE_URL)
    app.dependency_overrides.clear()
