from pathlib import Path

from sqlalchemy import Engine, event
from sqlmodel import SQLModel, create_engine

from brain_dock import models  # noqa: F401  (importing registers the tables)

# Local database at the repo root, inside the gitignored data/ folder.
DB_PATH = Path(__file__).parents[2] / "data" / "brain_dock.db"


def get_engine(url: str | None = None, **kwargs) -> Engine:
    """Create an engine with foreign keys enforced. Every engine should come from here."""
    # FastAPI runs routes in worker threads; each session still stays on one request,
    # so letting SQLite connections cross threads is safe here.
    kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(url or f"sqlite:///{DB_PATH}", **kwargs)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    # SQLite ignores foreign keys unless this is switched on, per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db(engine: Engine) -> None:
    """Create the database folder (for file databases) and any missing tables."""
    if engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


if __name__ == "__main__":
    create_db(get_engine())
    print("Database ready: data/brain_dock.db")
