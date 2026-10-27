from datetime import date

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, select

from brain_dock.core.db import (
    BASELINE_REVISION,
    ForeignKeyError,
    SchemaMismatchError,
    create_db,
    current_revision,
    get_engine,
    head_revision,
    is_at_head,
    migrate,
    schema_snapshot,
)
from brain_dock.modules.job_search.models import Company, RoleTrack, create_application


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def engine(db_file):
    engine = get_engine(f"sqlite:///{db_file}")
    yield engine
    engine.dispose()


def legacy_db(engine):
    """A database made the old way (create_all, no migration history), with one row."""
    create_db(engine)
    with Session(engine) as session:
        company = Company(name="Acme Analytics")
        session.add(company)
        create_application(session, company, "Engineer", RoleTrack.fde, date(2026, 10, 1))
        session.commit()


def company_names(engine):
    with Session(engine) as session:
        return list(session.exec(select(Company.name)))


def revision(engine):
    with engine.connect() as connection:
        return current_revision(connection)


# --- Migrations and models agree ---------------------------------------------


def test_migrations_match_the_models(engine, tmp_path):
    migrate(engine)

    # Alembic's own check: would autogenerate find anything to add? It shouldn't.
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
        migrated = schema_snapshot(connection)

    # And the schema is identical to what create_all builds from the models.
    plain = get_engine(f"sqlite:///{tmp_path / 'plain.db'}")
    create_db(plain)
    with plain.connect() as connection:
        assert schema_snapshot(connection) == migrated
    plain.dispose()


# --- Fresh databases ---------------------------------------------------------


def test_fresh_database_is_upgraded_to_head(engine, db_file):
    assert migrate(engine) == "upgraded"

    assert db_file.exists()
    assert revision(engine) == head_revision()
    assert {"company", "application", "stageevent"} <= set(inspect(engine).get_table_names())


def test_migrating_twice_is_a_no_op(engine):
    migrate(engine)

    assert migrate(engine) == "up to date"
    assert revision(engine) == head_revision()


# --- Existing create_all databases -------------------------------------------


def test_matching_legacy_database_is_stamped_and_keeps_its_data(engine):
    legacy_db(engine)
    assert revision(engine) is None
    assert not is_at_head(engine)

    assert migrate(engine) == "stamped"

    assert revision(engine) == head_revision()
    assert is_at_head(engine)
    assert company_names(engine) == ["Acme Analytics"]


@pytest.mark.parametrize(
    "change",
    [
        "ALTER TABLE company ADD COLUMN website VARCHAR",
        "DROP INDEX ix_company_name",
        "DROP TABLE stageevent",
    ],
)
def test_mismatched_legacy_database_is_not_stamped(engine, change):
    legacy_db(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(change)
        schema_before = schema_snapshot(connection)

    with pytest.raises(SchemaMismatchError, match=f"doesn't match migration {BASELINE_REVISION}"):
        migrate(engine)

    # Nothing changed: no version stamp, same schema, data still there.
    assert "alembic_version" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert schema_snapshot(connection) == schema_before
    assert company_names(engine) == ["Acme Analytics"]


def test_error_message_contains_no_data(engine):
    legacy_db(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE company ADD COLUMN website VARCHAR")

    with pytest.raises(SchemaMismatchError) as caught:
        migrate(engine)

    assert "Acme" not in str(caught.value)


# --- Foreign keys during migrations -------------------------------------------


def foreign_keys_on(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_migrate_refuses_rows_pointing_at_missing_rows(engine):
    migrate(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql(
            "INSERT INTO stageevent (application_id, stage, happened_on) "
            "VALUES (999, 'applied', '2026-10-01')"
        )
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    with pytest.raises(ForeignKeyError, match="Nothing was changed"):
        migrate(engine)
    assert foreign_keys_on(engine)
