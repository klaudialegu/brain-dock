import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from brain_dock import db, export
from brain_dock.db import create_db, get_engine

# The app only answers to its own host names (TrustedHostMiddleware), so test clients
# must use one of them instead of TestClient's default "testserver".
BASE_URL = "http://127.0.0.1:8000"

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
