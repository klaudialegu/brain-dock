"""To do: module #3 (ADR 0007, ADR 0015)."""

from pathlib import Path

from brain_dock.core.modules import Manifest, NavEntry
from brain_dock.modules.todo.brief import brief_lines
from brain_dock.modules.todo.card import CARD
from brain_dock.modules.todo.routes import router

MODULE_DIR = Path(__file__).parent

manifest = Manifest(
    name="todo",
    description="Tasks for today and for later, with optional steps.",
    home="/todo",
    router=router,
    paths=("/todo",),
    nav=(NavEntry("To do", "/todo"),),
    tables=("todo_task", "todo_step"),
    migrations=MODULE_DIR / "migrations",
    templates=MODULE_DIR / "templates",
    static=MODULE_DIR / "static",
    stylesheets=("/static/modules/todo/todo.css",),
    permissions=("storage",),
    brief=brief_lines,
    label="To do",
    color="graphite",
    icon="M10 7h10M10 12h10M10 17h10M4 7l1.2 1.2L7.5 6M4 12l1.2 1.2L7.5 11M4 17l1.2 1.2L7.5 16",
    cards=(CARD,),
)
