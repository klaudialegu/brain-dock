import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from brain_dock.db import create_db, get_engine


@pytest.fixture
def session():
    # A fresh in-memory database per test. StaticPool keeps one connection open,
    # because an in-memory SQLite database disappears when its connection closes.
    engine = get_engine("sqlite://", poolclass=StaticPool)
    create_db(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
