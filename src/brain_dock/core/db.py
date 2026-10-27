import os
from collections.abc import Mapping
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, event, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from brain_dock.core.agents import audit  # noqa: F401  (registers the core's own tables)

REPO_ROOT = Path(__file__).parents[3]  # src/brain_dock/core/db.py -> repo root
# Local databases at the repo root, inside the gitignored data/ folder.
DEFAULT_DB_PATH = REPO_ROOT / "data" / "brain_dock.db"
DEMO_DB_PATH = REPO_ROOT / "data" / "demo.db"


def database_path(environ: Mapping[str, str] = os.environ) -> Path:
    """The database the app and tools use: BRAIN_DOCK_DB if set, else data/brain_dock.db.
    A relative BRAIN_DOCK_DB is taken from the current folder (the repo root, per the README)."""
    configured = environ.get("BRAIN_DOCK_DB", "").strip()
    return Path(configured).resolve() if configured else DEFAULT_DB_PATH


def is_demo_database(path: Path) -> bool:
    return path.resolve() == DEMO_DB_PATH.resolve()


DB_PATH = database_path()
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
# The revision that matches databases made by create_all before migrations existed.
BASELINE_REVISION = "0001"


class SchemaMismatchError(RuntimeError):
    """An existing database doesn't match the schema it would be stamped as."""


class ForeignKeyError(RuntimeError):
    """A migration would leave a row pointing at a row that doesn't exist."""


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


def head_revisions() -> set[str]:
    """The latest revision of every module's branch."""
    return set(ScriptDirectory.from_config(_alembic_config()).get_heads())


def head_revision() -> str:
    return ", ".join(sorted(head_revisions()))


def current_revision(connection: Connection) -> str | None:
    """Where the database is, one revision per module branch (None before any migration)."""
    heads = MigrationContext.configure(connection).get_current_heads()
    return ", ".join(sorted(heads)) if heads else None


def schema_snapshot(connection: Connection) -> dict:
    """Tables, columns, keys, indexes and triggers, ignoring Alembic's own version table.
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
            "triggers": sorted(
                name
                for (name,) in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
                    (table,),
                )
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
    with engine.connect() as connection:
        # Batch migrations copy a table, drop it and rename the copy, while other tables
        # still point at it. SQLite only lets foreign keys be switched off outside a
        # transaction (its documented ALTER TABLE procedure), so: off, migrate in one
        # transaction, check every reference before committing, then back on.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("couldn't switch foreign keys off for the migration")
        connection.commit()
        try:
            with connection.begin():
                result = _migrate(connection)
                if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                    raise ForeignKeyError(
                        "The migration would leave rows pointing at missing rows. "
                        "Nothing was changed."
                    )
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
    return result


def _migrate(connection: Connection) -> str:
    """migrate() inside its transaction, with foreign keys off."""
    existing = set(inspect(connection).get_table_names())
    before = current_revision(connection)
    # Tables but no migration history: made before migrations existed (or by hand).
    # Only an exact match with the baseline is stamped; anything else stops.
    if before is None and existing - {"alembic_version"}:
        if schema_snapshot(connection) != baseline_snapshot():
            raise SchemaMismatchError(
                "The database has tables but no migration history, and its schema "
                f"doesn't match migration {BASELINE_REVISION}. Nothing was changed. "
                "Export or rebuild it before migrating."
            )
        command.stamp(_alembic_config(connection), BASELINE_REVISION)
        command.upgrade(_alembic_config(connection), "heads")
        return "stamped"
    command.upgrade(_alembic_config(connection), "heads")
    return "up to date" if before == head_revision() else "upgraded"


def is_at_head(engine: Engine) -> bool:
    with engine.connect() as connection:
        return current_revision(connection) == head_revision()


def display_path(path: Path) -> str:
    """A database path as people see it: relative to the repo when inside it, else in full."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def main() -> None:
    result = migrate(get_engine())
    # Name the database that was actually migrated (BRAIN_DOCK_DB can point anywhere).
    print(f"Database {result} at revision {head_revision()}: {display_path(DB_PATH)}")


if __name__ == "__main__":
    main()
