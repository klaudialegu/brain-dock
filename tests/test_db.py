from sqlalchemy import inspect

from brain_dock.core.db import DB_PATH, REPO_ROOT, create_db, get_engine


def test_create_db_makes_the_file_and_tables(tmp_path):
    path = tmp_path / "nested" / "test.db"
    engine = get_engine(f"sqlite:///{path}")

    create_db(engine)

    assert path.exists()
    assert set(inspect(engine).get_table_names()) == {
        "company",
        "application",
        "stageevent",
        "core_audit_event",
        "core_llm_call",
    }
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_default_database_lives_in_the_data_folder():
    assert DB_PATH.parent.name == "data"
    assert DB_PATH.name == "brain_dock.db"


def test_repo_root_is_the_project_folder():
    # REPO_ROOT is counted from this file's location (parents[N]). If a move changes that,
    # every path built from it (database, alembic.ini, backups, demo data) breaks silently.
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "alembic.ini").is_file()


def test_migrate_command_prints_the_database_it_migrated(tmp_path):
    import os
    import subprocess
    import sys

    # Outside the repo on purpose: the right answer differs from the default path, and the
    # test never writes into data/.
    target = (tmp_path / "migrated.db").resolve()
    env = dict(os.environ, BRAIN_DOCK_DB=str(target))
    result = subprocess.run(
        [sys.executable, "-m", "brain_dock.db"], env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert str(target) in result.stdout
    assert "data/brain_dock.db" not in result.stdout
    # It really migrated the file it names.
    from brain_dock.core.db import is_at_head

    engine = get_engine(f"sqlite:///{target}")
    assert target.exists() and is_at_head(engine)
    engine.dispose()
