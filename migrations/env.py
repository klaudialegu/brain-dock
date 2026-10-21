from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from brain_dock import models  # noqa: F401  (importing registers the tables)
from brain_dock.db import get_engine

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER most columns in place; batch mode copies the table instead.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# brain_dock.db.migrate() passes its own connection. On the command line, the
# default is data/brain_dock.db, or `-x db_url=sqlite:///path` for another file.
connection = config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    db_url = context.get_x_argument(as_dictionary=True).get("db_url")
    engine = get_engine(db_url)
    with engine.begin() as conn:
        run_migrations(conn)
    engine.dispose()
