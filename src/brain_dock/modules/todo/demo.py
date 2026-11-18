"""Load a few made-up tasks into the demo database, so the to-do page has something to
show: `uv run python -m brain_dock.modules.todo.demo`.

Always data/demo.db, never the real database, whatever BRAIN_DOCK_DB says.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

from sqlmodel import Session, select

from brain_dock.core import db
from brain_dock.modules.todo.models import TodoTask, add_step, add_task

NOT_READY = "The demo database isn't ready. Run: uv run python -m brain_dock.importer --demo"


def load_demo(path: Path, today: date | None = None) -> str:
    if not path.exists():  # checked first: connecting would create an empty file
        return NOT_READY
    today = today or date.today()
    engine = db.get_engine(f"sqlite:///{path}")
    try:
        if not db.is_at_head(engine):
            return NOT_READY
        with Session(engine) as session:
            if session.exec(select(TodoTask)).first() is not None:
                return f"{path.name} already has tasks: nothing loaded"
            write_up = add_task(
                session,
                "Finish the project write-up",
                estimate_minutes=45,
                due_on=today + timedelta(days=3),
            )
            for title, minutes in [
                ("Outline the three sections", 10),
                ("Draft the results section", 15),
                ("Add the before and after numbers", 10),
                ("Read it once out loud", 10),
            ]:
                add_step(session, write_up, title, minutes)
            add_task(session, "Water the plants", estimate_minutes=5, ok_to_read_aloud=True)
            add_task(session, "Order groceries", estimate_minutes=10, due_on=today)
            add_task(
                session,
                "Plan the weekend hike",
                bucket="can_wait",
                due_on=today + timedelta(days=2),
            )
            add_task(session, "Sort the photo folder", bucket="can_wait")
            session.commit()
    finally:
        engine.dispose()
    return f"Loaded 5 demo tasks into {path.name}"


def main() -> int:
    message = load_demo(db.DEMO_DB_PATH)
    print(message)
    return 0 if message.startswith("Loaded") or "already" in message else 1


if __name__ == "__main__":
    sys.exit(main())
