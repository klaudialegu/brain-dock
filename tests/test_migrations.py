from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, select

from brain_dock import registry
from brain_dock.core.db import (
    BASELINE_REVISION,
    ForeignKeyError,
    SchemaMismatchError,
    _alembic_config,
    create_db,
    current_revision,
    get_engine,
    head_revision,
    is_at_head,
    migrate,
    schema_snapshot,
)
from brain_dock.modules.job_search.models import (
    Company,
    RoleTrack,
    Stage,
    create_application,
    record_stage,
    save_interested,
)


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def engine(db_file):
    engine = get_engine(f"sqlite:///{db_file}")
    yield engine
    engine.dispose()


def legacy_db(engine):
    """A database made the old way (create_all, no migration history), with one row.

    Legacy databases were made by the models of their time, so this builds the schema of
    migration 0001 (create_all with today's models would be the newer schema) and then
    removes the migration history.
    """
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), BASELINE_REVISION)
        connection.execute(text("DROP TABLE alembic_version"))
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


# --- 0002: the interested stage -------------------------------------------------------


TABLES = ("company", "application", "stageevent")


def at_0001_with_rows(engine):
    """A database at migration 0001 holding two applications and their stage events."""
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), BASELINE_REVISION)
    with Session(engine) as session:
        company = Company(name="Acme Analytics")
        session.add(company)
        first = create_application(session, company, "Engineer", RoleTrack.fde, date(2026, 9, 1))
        create_application(session, company, "Support Lead", RoleTrack.support, date(2026, 9, 2))
        record_stage(session, first, Stage.screen, date(2026, 9, 5), note="Fake note")
        record_stage(session, first, Stage.withdrawn, date(2026, 9, 9))
        session.commit()


def all_rows(engine):
    with engine.connect() as connection:
        return {
            t: [tuple(r) for r in connection.exec_driver_sql(f"SELECT * FROM {t} ORDER BY id")]
            for t in TABLES
        }


def test_migration_0002_keeps_every_row(engine):
    at_0001_with_rows(engine)
    before = all_rows(engine)
    assert len(before["stageevent"]) == 4  # rows that point at applications really exist

    assert migrate(engine) == "upgraded"

    assert revision(engine) == head_revision()
    assert all_rows(engine) == before
    assert foreign_keys_on(engine)  # switched back on for the connections that follow
    with Session(engine) as session:  # and a saved job now fits
        save_interested(session, Company(name="Globex"), "Role", RoleTrack.fde, date(2026, 10, 1))
        session.commit()


def test_downgrade_refuses_while_saved_jobs_exist(engine):
    migrate(engine)
    with Session(engine) as session:
        save_interested(session, Company(name="Acme"), "Role", RoleTrack.fde, date(2026, 10, 1))
        session.commit()

    with engine.begin() as connection, pytest.raises(RuntimeError, match="1 saved job"):
        command.downgrade(_alembic_config(connection), "job_search@0001")
    assert revision(engine) == head_revision()


# --- The core's own branch (ADR 0008) ---------------------------------------------------


def test_core_migrations_are_a_branch_of_their_own():
    from pathlib import Path

    from alembic.script import ScriptDirectory

    from brain_dock.core.db import REPO_ROOT

    core = REPO_ROOT / "src" / "brain_dock" / "core" / "migrations"
    scripts = ScriptDirectory.from_config(_alembic_config())
    own = [s for s in scripts.walk_revisions() if Path(s.path).parent == core]

    assert own  # the core really has migrations
    starts = [s for s in own if s.down_revision is None]
    assert [s.revision for s in starts] == ["core_0001"] and "core" in starts[0].branch_labels
    ids = {s.revision for s in own}
    for script in own:
        parents = script.down_revision
        for parent in (
            () if parents is None else parents if isinstance(parents, tuple) else (parents,)
        ):
            assert parent in ids, f"{script.revision} builds on {parent} from elsewhere"
    # The core's tables are prefixed, so they can never clash with a module's.
    core_tables = {t for t in SQLModel.metadata.tables if t.startswith("core_")}
    module_tables = {t for m in registry.installed() for t in m.tables}
    assert core_tables == {
        "core_audit_event",
        "core_llm_call",
        "core_agent_run",
        "core_work_item",
        "core_run_step",
        "core_approval",
    }
    assert set(SQLModel.metadata.tables) == core_tables | module_tables


def test_migration_core_0002_keeps_every_row_and_the_audit_chain(engine):
    from brain_dock.core.agents.audit import AuditKey, AuditLog, verify_chain

    at_0001_with_rows(engine)
    with engine.begin() as connection:  # the core at core_0001, before the ledger
        command.upgrade(_alembic_config(connection), "core@core_0001")
    key = AuditKey(b"k" * 32)
    log = AuditLog(engine, key)
    for n in range(3):
        log.record(
            run_id="r", module="inbox", tool="t", outcome="allowed", reason="ok", input_mac=str(n)
        )
    before = all_rows(engine)
    with engine.connect() as connection:
        audit_before = list(
            connection.exec_driver_sql("SELECT * FROM core_audit_event ORDER BY id")
        )

    with engine.begin() as connection:  # exactly this migration, not whatever is newest
        command.upgrade(_alembic_config(connection), "core@core_0002")

    assert "core_0002" in revision(engine)
    assert all_rows(engine) == before
    with engine.connect() as connection:
        audit_after = list(connection.exec_driver_sql("SELECT * FROM core_audit_event ORDER BY id"))
    assert audit_after == audit_before and len(audit_after) == 3
    assert verify_chain(engine, key).ok


def test_migration_core_0003_marks_unknown_costs_null(engine):
    at_0001_with_rows(engine)
    with engine.begin() as connection:  # the ledger as it was: unknown costs stored as 0
        command.upgrade(_alembic_config(connection), "core@core_0002")
        for outcome, cost in [
            ("ok", 4100),
            ("timeout", 0),
            ("server_error", 0),
            ("failed", 0),
            ("started", 0),
            ("budget_stopped", 0),
            ("refused", 2000),
        ]:
            connection.exec_driver_sql(
                "INSERT INTO core_llm_call (at, run_id, module, route, model, prompt_version, "
                "attempt, outcome, input_tokens, output_tokens, cache_read_tokens, "
                "cache_write_tokens, cost_micro_usd, prices_verified) VALUES "
                "('2026-10-26 12:00:00', 'r', 'inbox', 'cheap', 'm', 'v1', 1, ?, 0, 0, 0, 0, ?, 0)",
                (outcome, cost),
            )

    migrate(engine)

    with engine.connect() as connection:
        rows = connection.exec_driver_sql("SELECT outcome, cost_micro_usd FROM core_llm_call")
        costs = {outcome: cost for outcome, cost in rows}
    assert costs == {
        "ok": 4100,
        "timeout": None,
        "server_error": None,
        "failed": None,
        "started": None,
        "budget_stopped": 0,  # free: nothing was sent
        "refused": 2000,
    }


def test_migration_core_0004_keeps_every_row(engine):
    from brain_dock.core.agents.audit import AuditKey, AuditLog, verify_chain

    at_0001_with_rows(engine)
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), "core@core_0003")
        connection.exec_driver_sql(
            "INSERT INTO core_llm_call (at, run_id, module, route, model, prompt_version, "
            "attempt, outcome, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_tokens, cost_micro_usd, prices_verified) VALUES "
            "('2026-10-26 12:00:00', 'r', 'inbox', 'cheap', 'm', 'v1', 1, 'timeout', "
            "0, 0, 0, 0, NULL, 0)"
        )
    key = AuditKey(b"k" * 32)
    AuditLog(engine, key).record(
        run_id="r", module="inbox", tool="t", outcome="allowed", reason="ok", input_mac="x"
    )
    tables = ("company", "application", "stageevent", "core_audit_event", "core_llm_call")

    def everything():
        with engine.connect() as connection:
            return {
                t: [tuple(r) for r in connection.exec_driver_sql(f"SELECT * FROM {t} ORDER BY id")]
                for t in tables
            }

    before = everything()

    with engine.begin() as connection:  # exactly this migration, not whatever is newest
        command.upgrade(_alembic_config(connection), "core@core_0004")

    assert "core_0004" in revision(engine)
    assert everything() == before
    assert verify_chain(engine, key).ok


def test_migration_core_0005_keeps_every_row(engine):
    at_0001_with_rows(engine)
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), "core@core_0004")
        connection.exec_driver_sql(
            "INSERT INTO core_work_item (module, key, state, attempts, created_at, updated_at) "
            "VALUES ('inbox', 'abc123', 'received', 0, '2026-10-26 12:00:00', "
            "'2026-10-26 12:00:00')"
        )
    tables = ("company", "application", "stageevent", "core_work_item")

    def everything():
        with engine.connect() as connection:
            return {
                t: [tuple(r) for r in connection.exec_driver_sql(f"SELECT * FROM {t} ORDER BY id")]
                for t in tables
            }

    before = everything()

    with engine.begin() as connection:  # exactly this migration, not whatever is newest
        command.upgrade(_alembic_config(connection), "core@core_0005")

    assert "core_0005" in revision(engine)
    assert everything() == before
