"""The daily brief as text (ADR 0013): a greeting, then each enabled module's lines.

Modules add lines through their manifest's `brief`, so this file never reaches into a
module's tables. `uv run python -m brain_dock.brief` prints it and sends nothing.
"""

import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date

from sqlmodel import Session

from brain_dock import registry
from brain_dock.core import db
from brain_dock.core.db import get_engine, is_at_head
from brain_dock.core.modules import Manifest

# Text-to-speech is billed per character, so the brief has a hard cap (about $0.024 a
# generation at ElevenLabs' Flash price).
MAX_BRIEF_CHARS = 600
CLOSING = "More in the app."
NOTHING = "Nothing needs your attention today."


def greeting(today: date) -> str:
    return f"Good morning. Here's your brief for {today:%A, %B} {today.day}."


def cap(lines: list[str], limit: int = MAX_BRIEF_CHARS) -> str:
    """Join the lines; past the cap, drop whole lines (never cut one) and say there's more."""
    text = " ".join(lines)
    if len(text) <= limit:
        return text
    kept: list[str] = []
    for line in lines:
        if len(" ".join([*kept, line, CLOSING])) > limit:
            break
        kept.append(line)
    return " ".join([*kept, CLOSING])


def build_brief(session: Session, today: date, modules: Iterable[Manifest]) -> str:
    body = [line for m in modules if m.brief for line in m.brief(session, today)]
    return cap([greeting(today), *(body or [NOTHING])])


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
    """Each enabled module's lines for today, by module name, in nav order."""
    with database_session() as session:
        today = today or date.today()
        return {m.name: m.brief(session, today) for m in registry.enabled() if m.brief}


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
