"""The inbox's card on Home (ADR 0016): how many roles wait for a decision."""

from sqlmodel import func, select

from brain_dock.core.agents.run_tables import Approval
from brain_dock.core.modules import Card, CardContext, CardView


def render(ctx: CardContext) -> CardView:
    waiting = ctx.session.exec(
        select(func.count())
        .select_from(Approval)
        .where(Approval.module == "inbox", Approval.status == "pending")
    ).one()
    return CardView(
        "inbox/card.html", {"waiting": waiting}, empty=not waiting, empty_line="Nothing waiting."
    )


CARD = Card(
    id="inbox",
    label="Inbox",
    color="sky",
    render=render,
    sizes=("S", "M"),
    default_size="S",
    rank=50,
)
