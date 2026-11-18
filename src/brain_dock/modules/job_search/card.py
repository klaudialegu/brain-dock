"""Career Radar's card on Home (ADR 0016): the latest open applications."""

from brain_dock.core.modules import Card, CardContext, CardView
from brain_dock.modules.job_search.queries import list_applications
from brain_dock.modules.job_search.stages import STAGES

SHOWN = 3


def _open(session):
    return [a for a in list_applications(session) if STAGES[a.current_stage].kind != "closed"]


def render(ctx: CardContext) -> CardView:
    rows = _open(ctx.session)
    return CardView(
        "job_search/card.html",
        {"rows": rows[:SHOWN], "more": max(0, len(rows) - SHOWN)},
        empty=not rows,
        empty_line="No open applications.",
    )


def follow_up_due(ctx: CardContext) -> bool:
    """The ring: a follow-up is due today or overdue."""
    return any(
        a.follow_up_on is not None and a.follow_up_on <= ctx.today for a in _open(ctx.session)
    )


CARD = Card(
    id="job_search",
    label="Career Radar",
    color="sage",
    render=render,
    sizes=("M", "L", "W"),
    default_size="L",
    attention=follow_up_due,
    rank=30,
)
