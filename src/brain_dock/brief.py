"""The daily brief as text, from the command line (ADR 0013): `uv run python -m
brain_dock.brief` prints it and sends nothing. The brief itself is built in the core
(core/brief.py); this file adds the configured database and the enabled modules.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from sqlmodel import Session

from brain_dock import registry
from brain_dock.core import db
from brain_dock.core.brief import (  # noqa: F401  (also the names other code uses)
    CLOSING,
    MAX_BRIEF_CHARS,
    NOTHING,
    build_brief,
    cap,
    greeting,
    lines_by_module,
)
from brain_dock.core.db import get_engine, is_at_head


@contextmanager
def database_session() -> Iterator[Session]:
    """The configured database (BRAIN_DOCK_DB, or data/brain_dock.db), checked first."""
    if not db.DB_PATH.exists():
        raise RuntimeError("No database yet. Run: uv run python -m brain_dock.db")
    engine = get_engine()
    try:
        if not is_at_head(engine):
            raise RuntimeError("The database needs migrating. Run: uv run python -m brain_dock.db")
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def module_lines(today: date | None = None) -> dict[str, list[str]]:
    """Each enabled and shown module's lines for today, by module name, in nav order."""
    with database_session() as session:
        return lines_by_module(session, today or date.today(), registry.enabled())


def current_brief(today: date | None = None) -> str:
    """Today's brief from the configured database."""
    today = today or date.today()
    lines = [line for module in module_lines(today).values() for line in module]
    return cap([greeting(today), *(lines or [NOTHING])])


def main() -> int:
    try:
        text = current_brief()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    print(text)
    print(f"({len(text)} characters; nothing was sent anywhere)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
