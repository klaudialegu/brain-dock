from sqlalchemy import inspect

from brain_dock.db import DB_PATH, create_db, get_engine


def test_create_db_makes_the_file_and_tables(tmp_path):
    path = tmp_path / "nested" / "test.db"
    engine = get_engine(f"sqlite:///{path}")

    create_db(engine)

    assert path.exists()
    assert set(inspect(engine).get_table_names()) == {"company", "application", "stageevent"}
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_default_database_lives_in_the_data_folder():
    assert DB_PATH.parent.name == "data"
    assert DB_PATH.name == "brain_dock.db"
