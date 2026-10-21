from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, event, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from brain_dock import models  # noqa: F401  (importing registers the tables)

REPO_ROOT = Path(__file__).parents[2]
# Local database at the repo root, inside the gitignored data/ folder.
DB_PATH = REPO_ROOT / "data" / "brain_dock.db"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
# The revision that matches databases made by create_all before migrations existed.
BASELINE_REVISION = "0001"
TRACKER_TABLES = {"company", "application", "stageevent"}


class SchemaMismatchError(RuntimeError):
    """An existing database doesn't match the schema it would be stamped as."""


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
    """Create tables straight from the models. Only for throwaway in-memory test
    databases; real databases go through migrate()."""
    if engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def _alembic_config(connection: Connection | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(_alembic_config()).get_current_head()


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def schema_snapshot(connection: Connection) -> dict:
    """Tables, columns, keys and indexes, ignoring Alembic's own version table.
    Structure only: it never reads any rows."""
    inspector = inspect(connection)
    snapshot = {}
    for table in sorted(set(inspector.get_table_names()) - {"alembic_version"}):
        snapshot[table] = {
            "columns": [
                (c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)
            ],
            "primary_key": inspector.get_pk_constraint(table)["constrained_columns"],
            "foreign_keys": sorted(
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                )
                for fk in inspector.get_foreign_keys(table)
            ),
            "indexes": sorted(
                (ix["name"], tuple(ix["column_names"]), bool(ix["unique"]))
                for ix in inspector.get_indexes(table)
            ),
        }
    return snapshot


def baseline_snapshot() -> dict:
    """The schema migration 0001 creates, built in a throwaway in-memory database."""
    engine = get_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), BASELINE_REVISION)
        snapshot = schema_snapshot(connection)
    engine.dispose()
    return snapshot


def migrate(engine: Engine) -> str:
    """Bring the database to the latest migration and say what happened:
    "upgraded", "up to date", or "stamped" (an existing create_all database whose
    schema was checked against migration 0001 first)."""
    if engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        before = current_revision(connection)
        if before is None and existing & TRACKER_TABLES:
            if schema_snapshot(connection) != baseline_snapshot():
                raise SchemaMismatchError(
                    "The database has tables but no migration history, and its schema "
                    f"doesn't match migration {BASELINE_REVISION}. Nothing was changed. "
                    "Export or rebuild it before migrating."
                )
            command.stamp(_alembic_config(connection), BASELINE_REVISION)
            command.upgrade(_alembic_config(connection), "head")
            return "stamped"
        command.upgrade(_alembic_config(connection), "head")
        return "up to date" if before == head_revision() else "upgraded"


def is_at_head(engine: Engine) -> bool:
    with engine.connect() as connection:
        return current_revision(connection) == head_revision()


if __name__ == "__main__":
    result = migrate(get_engine())
    print(f"Database {result} at revision {head_revision()}: data/brain_dock.db")
