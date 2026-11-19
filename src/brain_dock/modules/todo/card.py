"""To do's card on Home (ADR 0016): Today with checkboxes, dot meters, steps that open
inline, the read-aloud toggle and a Focus link; then a quieter Can wait. Plain forms with
CSRF that come back to Home (a fixed `back` word, never an address)."""

from brain_dock.core.modules import Card, CardContext, CardView
from brain_dock.modules.todo.models import card as todo_lists
from brain_dock.modules.todo.models import dot_count, live_steps, meta, when_label

SHOWN = 6
CAN_WAIT_SHOWN = 3


def render(ctx: CardContext) -> CardView:
    today_list, can_wait = todo_lists(ctx.session, ctx.today)
    rows = [
        {"task": t, "meta": meta(t, ctx.today), "dots": dot_count(t), "steps": live_steps(t)}
        for t in today_list[:SHOWN]
    ]
    return CardView(
        "todo/card.html",
        {
            "rows": rows,
            "more": max(0, len(today_list) - SHOWN),
            "can_wait": [(t, when_label(t.due_on, ctx.today)) for t in can_wait[:CAN_WAIT_SHOWN]],
            "can_wait_more": max(0, len(can_wait) - CAN_WAIT_SHOWN),
            "open": sum(1 for t in today_list if not t.done),
        },
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
