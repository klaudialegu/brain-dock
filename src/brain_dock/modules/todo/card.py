"""To do's card on Home (ADR 0016). A simple list for now; the full card (dot meters,
steps, the read-aloud toggle, Focus) comes in its own slice."""

from brain_dock.core.modules import Card, CardContext, CardView
from brain_dock.modules.todo.models import card as todo_lists
from brain_dock.modules.todo.models import meta

SHOWN = 6


def render(ctx: CardContext) -> CardView:
    today_list, can_wait = todo_lists(ctx.session, ctx.today)
    rows = [(t, meta(t, ctx.today)) for t in today_list[:SHOWN]]
    return CardView(
        "todo/card.html",
        {"rows": rows, "can_wait": len(can_wait), "open": sum(1 for t in today_list if not t.done)},
        empty=not today_list and not can_wait,
        empty_line="Nothing on the list. Add a task when something comes up.",
    )


def overdue(ctx: CardContext) -> bool:
    today_list, _ = todo_lists(ctx.session, ctx.today)
    return any(not t.done and t.due_on is not None and t.due_on < ctx.today for t in today_list)


CARD = Card(
    id="todo",
    label="To do",
    color="graphite",
    render=render,
    sizes=("L", "W"),
    default_size="W",
    attention=overdue,
    rank=10,
)
