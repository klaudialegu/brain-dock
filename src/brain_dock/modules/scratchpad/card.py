"""The Scratchpad's card on Home (ADR 0016, 0017): the last lines of the latest page, on
its paper. A playful card, so it lives in Home's side area."""

from brain_dock.core.modules import Card, CardContext, CardView
from brain_dock.modules.scratchpad.models import latest, text_layer

SHOWN_LINES = 5


def render(ctx: CardContext) -> CardView:
    page = latest(ctx.session)
    lines = [ln for ln in text_layer(page).content.splitlines() if ln.strip()] if page else []
    return CardView(
        "scratchpad/card.html",
        {"page": page, "lines": lines[-SHOWN_LINES:]},
        empty=not lines,
        empty_line="A clean page. Jot something down.",
    )


CARD = Card(
    id="scratchpad",
    label="Scratchpad",
    color="butter",
    render=render,
    sizes=("M",),
    default_size="M",
    side=True,
    rank=60,
)
