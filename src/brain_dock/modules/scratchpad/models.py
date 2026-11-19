"""Scratchpad pages (ADR 0017): pages by day, each a stack of layers. Typing only for now:
a page has one text layer; a drawing ("ink") layer can be added later without a migration.

Text is personal data: it stays in the local database, is never logged, never reaches the
brief, and is never sent anywhere. Pen, paper and size are saved per page.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, Session, SQLModel, func, select

TEXT_MAX = 20_000  # characters on one page
CAPTURE_MAX = 2_000  # characters in one quick note


@dataclass(frozen=True)
class Pen:
    key: str
    name: str
    spec: str
    ink: str  # 4.5:1 or better on every paper (tests/test_scratchpad.py)
    available: bool = True


PENS = {
    p.key: p
    for p in [
        Pen("fineliner", "Fineliner", "0.4 · black", "#1D1B18"),
        Pen("gel", "Gel pen", "0.5 · blue", "#335A96"),
        Pen("pencil", "Pencil", "HB · graphite", "#5F5A52"),
        Pen("brush", "Brush pen", "soft · sepia", "#6B4A2B"),
        Pen("rose", "Rose gel", "0.5 · rose", "#8E3F5C"),
        Pen("highlighter", "Highlighter", "sage, ink on top", "#1D1B18"),
        Pen("eraser", "Eraser", "for drawing, later", "#1D1B18", available=False),
    ]
}
PAPERS = {
    "blank": "Blank",
    "lined": "Lined",
    "squared": "Squared",
    "dotted": "Dotted",
    "kraft": "Kraft",
}
PAPER_COLORS = {
    "blank": "#FFFEFB",
    "lined": "#FFFEFB",
    "squared": "#FFFEFB",
    "dotted": "#FFFEFB",
    "kraft": "#EADCC3",
}
SIZES = {"card": "Card", "wide": "Wide", "full": "Full"}


class ScratchpadPage(SQLModel, table=True):
    __tablename__ = "scratchpad_page"
    __table_args__ = (UniqueConstraint("day", "position", name="uq_scratchpad_page_day"),)

    id: int | None = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    position: int  # 1, 2, 3… within its day
    paper: str = "lined"
    pen: str = "fineliner"
    size: str = "wide"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    removed_at: datetime | None = None  # removed: out of tabs, card and capture (ADR 0018)

    layers: list["ScratchpadLayer"] = Relationship(
        back_populates="page",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "ScratchpadLayer.position",
        },
    )


class ScratchpadLayer(SQLModel, table=True):
    __tablename__ = "scratchpad_layer"
    __table_args__ = (UniqueConstraint("page_id", "position", name="uq_scratchpad_layer_order"),)

    id: int | None = Field(default=None, primary_key=True)
    page_id: int = Field(foreign_key="scratchpad_page.id", index=True, ondelete="CASCADE")
    kind: str = "text"  # "text" now; "ink" for drawing later
    position: int  # stacking order, bottom first
    content: str = ""

    page: ScratchpadPage | None = Relationship(back_populates="layers")


class ScratchpadError(ValueError):
    """A value that isn't allowed. The message names the field, never what was typed."""


def new_page(session: Session, day: date) -> ScratchpadPage:
    """A fresh page for that day, after its other pages. Pen and paper carry over from
    the day's last page, so a second page looks like the first. The caller commits."""
    last = latest_on(session, day)
    page = ScratchpadPage(
        day=day,
        position=next_position(session, day),
        paper=last.paper if last else "lined",
        pen=last.pen if last else "fineliner",
        size=last.size if last else "wide",
    )
    page.layers.append(ScratchpadLayer(kind="text", position=0))
    session.add(page)
    return page


def next_position(session: Session, day: date) -> int:
    """After every page that day, removed ones included, so a number is never reused (the
    day+position rule would refuse it, and Undo needs the old page's place)."""
    highest = session.exec(
        select(func.max(ScratchpadPage.position)).where(ScratchpadPage.day == day)
    ).one()
    return (highest or 0) + 1


def is_empty(page: ScratchpadPage) -> bool:
    return not text_layer(page).content.strip()


def latest_on(session: Session, day: date) -> ScratchpadPage | None:
    """That day's last page that isn't removed."""
    return session.exec(
        select(ScratchpadPage)
        .where(ScratchpadPage.day == day, ScratchpadPage.removed_at == None)  # noqa: E711
        .order_by(ScratchpadPage.position.desc())
    ).first()


def shown(page: ScratchpadPage, today: date) -> bool:
    """Listed in the tabs and opened by /scratchpad: not removed, and not an empty page
    left over from an earlier day."""
    return page.removed_at is None and (page.day >= today or not is_empty(page))


def latest(session: Session, today: date | None = None) -> ScratchpadPage | None:
    today = today or date.today()
    pages = session.exec(
        select(ScratchpadPage)
        .where(ScratchpadPage.removed_at == None)  # noqa: E711
        .order_by(ScratchpadPage.day.desc(), ScratchpadPage.position.desc())
    ).all()
    return next((p for p in pages if shown(p, today)), None)


def pages_by_day(
    session: Session, days: int = 7, today: date | None = None
) -> list[tuple[date, list[ScratchpadPage]]]:
    """The most recent days with pages to show, newest first; each day's pages in order.
    Hidden pages are filtered out before days are counted, so they take no slot."""
    today = today or date.today()
    pages = session.exec(
        select(ScratchpadPage)
        .where(ScratchpadPage.removed_at == None)  # noqa: E711
        .order_by(ScratchpadPage.day.desc(), ScratchpadPage.position)
    ).all()
    grouped: dict[date, list[ScratchpadPage]] = {}
    for page in pages:
        if not shown(page, today):
            continue
        if page.day in grouped or len(grouped) < days:
            grouped.setdefault(page.day, []).append(page)
    return list(grouped.items())


def remove_page(page: ScratchpadPage, now: datetime | None = None) -> None:
    if page.removed_at is not None:
        raise ScratchpadError("Page: already removed")
    page.removed_at = now or datetime.now(UTC)


def restore_page(page: ScratchpadPage) -> None:
    if page.removed_at is None:
        raise ScratchpadError("Page: not removed")
    page.removed_at = None


def text_layer(page: ScratchpadPage) -> ScratchpadLayer:
    for layer in page.layers:
        if layer.kind == "text":
            return layer
    layer = ScratchpadLayer(kind="text", position=len(page.layers))
    page.layers.append(layer)
    return layer


def set_text(page: ScratchpadPage, text: str) -> None:
    text = text.replace("\r\n", "\n")
    if len(text) > TEXT_MAX:
        raise ScratchpadError(f"Text: at most {TEXT_MAX:,} characters on a page")
    text_layer(page).content = text


def revision(page: ScratchpadPage) -> str:
    """A fingerprint of the page's text. The page form carries the one it loaded, so a save
    from a tab opened before a quick note landed can't silently replace that note."""
    return hashlib.sha256(text_layer(page).content.encode()).hexdigest()[:16]


def with_new_lines(typed: str, saved: str) -> str:
    """For a refused save: the typed text, plus any saved line it doesn't have (quick notes
    only ever add lines), at the end. Keeping a line twice beats losing one."""
    typed = typed.replace("\r\n", "\n")
    have = set(typed.split("\n"))
    extra = [line for line in saved.split("\n") if line.strip() and line not in have]
    if not extra:
        return typed
    return "\n".join([typed.rstrip("\n"), *extra]) if typed.strip() else "\n".join(extra)


def append_line(session: Session, day: date, line: str) -> ScratchpadPage:
    """Quick capture: one line at the end of that day's latest page. A new page is made if
    there's none yet, or if the line wouldn't fit on it, so a note is never dropped."""
    line = " ".join(line.split())
    if not line:
        raise ScratchpadError("Note: write something first")
    if len(line) > CAPTURE_MAX:
        raise ScratchpadError(f"Note: at most {CAPTURE_MAX:,} characters")
    page = latest_on(session, day) or new_page(session, day)
    content = text_layer(page).content.rstrip("\n")
    joined = f"{content}\n{line}" if content else line
    if len(joined) > TEXT_MAX:
        page, joined = new_page(session, day), line
    set_text(page, joined)
    return page


def set_style(
    page: ScratchpadPage,
    *,
    pen: str | None = None,
    paper: str | None = None,
    size: str | None = None,
) -> None:
    if pen is not None:
        if pen not in PENS or not PENS[pen].available:
            raise ScratchpadError("Pen: one from the tray")
        page.pen = pen
    if paper is not None:
        if paper not in PAPERS:
            raise ScratchpadError("Paper: one of the five papers")
        page.paper = paper
    if size is not None:
        if size not in SIZES:
            raise ScratchpadError("Size: card, wide or full")
        page.size = size
