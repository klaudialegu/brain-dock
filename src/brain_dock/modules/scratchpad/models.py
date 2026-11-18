"""Scratchpad pages (ADR 0017): pages by day, each a stack of layers. Typing only for now:
a page has one text layer; a drawing ("ink") layer can be added later without a migration.

Text is personal data: it stays in the local database, is never logged, never reaches the
brief, and is never sent anywhere. Pen, paper and size are saved per page.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, Session, SQLModel, select

TEXT_MAX = 20_000
CAPTURE_MAX = 2_000  # one quick note  # characters on one page


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
        position=(last.position + 1) if last else 1,
        paper=last.paper if last else "lined",
        pen=last.pen if last else "fineliner",
        size=last.size if last else "wide",
    )
    page.layers.append(ScratchpadLayer(kind="text", position=0))
    session.add(page)
    return page


def latest_on(session: Session, day: date) -> ScratchpadPage | None:
    return session.exec(
        select(ScratchpadPage)
        .where(ScratchpadPage.day == day)
        .order_by(ScratchpadPage.position.desc())
    ).first()


def latest(session: Session) -> ScratchpadPage | None:
    return session.exec(
        select(ScratchpadPage).order_by(ScratchpadPage.day.desc(), ScratchpadPage.position.desc())
    ).first()


def pages_by_day(session: Session, days: int = 7) -> list[tuple[date, list[ScratchpadPage]]]:
    """The most recent days that have pages, newest first; each day's pages in order."""
    pages = session.exec(
        select(ScratchpadPage).order_by(ScratchpadPage.day.desc(), ScratchpadPage.position)
    ).all()
    grouped: dict[date, list[ScratchpadPage]] = {}
    for page in pages:
        if page.day in grouped or len(grouped) < days:
            grouped.setdefault(page.day, []).append(page)
    return list(grouped.items())


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
