"""Home's layout and the shell's settings, saved in the database (ADR 0016).

A card with no saved row uses its manifest's defaults, so a fresh database needs no rows.
Turning a card off in Settings is soft (ADR 0016): its module's pages and data stay. A
module whose cards are all off leaves Home, the rail and the brief.
"""

from dataclasses import dataclass

from sqlmodel import Session, select

from brain_dock.core.layout_tables import CoreLayout, CoreSetting
from brain_dock.core.modules import SIZES, Card, Manifest
from brain_dock.core.palette import DEFAULT_HIGHLIGHTER, PALETTE


class LayoutError(ValueError):
    """A layout change that isn't allowed (an unknown card, or a size it doesn't support)."""


@dataclass(frozen=True)
class Placed:
    card: Card
    module: Manifest | None  # None for the core's own cards
    position: int
    shown: bool
    size: str


def all_cards(modules, core_cards=()) -> list[tuple[Card, Manifest | None]]:
    """Every card in its default order: by rank, then core cards and modules in nav order."""
    cards = [(c, None) for c in core_cards] + [(c, m) for m in modules for c in m.cards]
    return sorted(cards, key=lambda pair: pair[0].rank)  # stable: ties keep nav order


def layout(session: Session, modules, core_cards=()) -> list[Placed]:
    """Every card in its saved (or default) position, shown or not."""
    saved = {row.card_id: row for row in session.exec(select(CoreLayout)).all()}
    placed = []
    for default_position, (card, module) in enumerate(all_cards(modules, core_cards)):
        row = saved.get(card.id)
        default_shown = card.default_shown and not (module and module.off_by_default)
        size = row.size if row and row.size in card.sizes else card.default_size
        placed.append(
            Placed(
                card=card,
                module=module,
                position=row.position if row else 1000 + default_position,
                shown=row.shown if row else default_shown,
                size=size,
            )
        )
    return sorted(placed, key=lambda p: p.position)


def _save(session: Session, placed: list[Placed]) -> None:
    """Writes every card's row with positions 0, 1, 2…, so order is explicit once changed."""
    for position, p in enumerate(placed):
        row = session.get(CoreLayout, p.card.id) or CoreLayout(
            card_id=p.card.id, position=0, shown=p.shown, size=p.size
        )
        row.position, row.shown, row.size = position, p.shown, p.size
        session.add(row)


def _find(placed: list[Placed], card_id: str) -> int:
    for i, p in enumerate(placed):
        if p.card.id == card_id:
            return i
    raise LayoutError("unknown card")


def move(session: Session, modules, card_id: str, direction: int, core_cards=()) -> None:
    placed = layout(session, modules, core_cards)
    i = _find(placed, card_id)
    j = i + direction
    if 0 <= j < len(placed):
        placed[i], placed[j] = placed[j], placed[i]
    _save(session, placed)


def set_shown(session: Session, modules, card_id: str, shown: bool, core_cards=()) -> None:
    placed = layout(session, modules, core_cards)
    i = _find(placed, card_id)
    p = placed[i]
    placed[i] = Placed(p.card, p.module, p.position, shown, p.size)
    _save(session, placed)


def set_size(session: Session, modules, card_id: str, size: str, core_cards=()) -> None:
    placed = layout(session, modules, core_cards)
    i = _find(placed, card_id)
    p = placed[i]
    if size not in p.card.sizes or size not in SIZES:
        raise LayoutError("that size isn't available for this card")
    placed[i] = Placed(p.card, p.module, p.position, p.shown, size)
    _save(session, placed)


def hidden_modules(session: Session, modules, core_cards=()) -> set[str]:
    """Modules with cards, all of them turned off. They leave Home, the rail and the brief."""
    shown: dict[str, bool] = {}
    for p in layout(session, modules, core_cards):
        if p.module is not None:
            shown[p.module.name] = shown.get(p.module.name, False) or p.shown
    return {name for name, any_shown in shown.items() if not any_shown}


def visible_modules(session: Session, modules, core_cards=()) -> list[Manifest]:
    hidden = hidden_modules(session, modules, core_cards)
    return [m for m in modules if m.name not in hidden]


def highlighter(session: Session) -> str:
    """The highlighter of the day: a palette name."""
    row = session.get(CoreSetting, "highlighter")
    return row.value if row and row.value in PALETTE else DEFAULT_HIGHLIGHTER


def set_highlighter(session: Session, name: str) -> None:
    if name not in PALETTE:
        raise LayoutError("that isn't one of the highlighters")
    row = session.get(CoreSetting, "highlighter") or CoreSetting(key="highlighter", value=name)
    row.value = name
    session.add(row)
