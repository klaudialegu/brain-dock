"""Load a made-up scratchpad page into the demo database, so the Scratchpad has something
to show: `uv run python -m brain_dock.modules.scratchpad.demo`.

Always data/demo.db, never the real database, whatever BRAIN_DOCK_DB says.
"""

import sys
from datetime import date
from pathlib import Path

from sqlmodel import Session, select

from brain_dock.core import db
from brain_dock.modules.scratchpad.models import ScratchpadPage, new_page, set_text

NOT_READY = "The demo database isn't ready. Run: uv run python -m brain_dock.importer --demo"
LINES = [
    "weekend: repot the basil",
    "idea: a shorter Monday list",
    "call the library about the hold",
    "oat milk, lemons",
]


def load_demo(path: Path, today: date | None = None) -> str:
    if not path.exists():  # checked first: connecting would create an empty file
        return NOT_READY
    engine = db.get_engine(f"sqlite:///{path}")
    try:
        if not db.is_at_head(engine):
            return NOT_READY
        with Session(engine) as session:
            if session.exec(select(ScratchpadPage)).first() is not None:
                return f"{path.name} already has scratchpad pages: nothing loaded"
            page = new_page(session, today or date.today())
            set_text(page, "\n".join(LINES))
            session.commit()
    finally:
        engine.dispose()
    return f"Loaded 1 demo scratchpad page into {path.name}"


def main() -> int:
    message = load_demo(db.DEMO_DB_PATH)
    print(message)
    return 0 if message.startswith("Loaded") or "already" in message else 1


if __name__ == "__main__":
    sys.exit(main())
