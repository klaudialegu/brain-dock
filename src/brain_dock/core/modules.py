"""What a module is: a manifest the core reads (ADR 0007). Modules import this; the core
never imports a module."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from fastapi import APIRouter
from sqlmodel import Session

from brain_dock.core.agents.tools import AgentTool


@dataclass(frozen=True)
class NavEntry:
    label: str
    path: str


# Card widths on Home's 12-column grid (ADR 0016).
SIZES = {"S": 3, "M": 4, "L": 5, "W": 8}
STATES = ("calm", "empty", "attention")


@dataclass(frozen=True)
class CardContext:
    """What a card's render function gets: the session, today, and the modules shown on
    Home (the brief card needs them; most cards don't)."""

    session: Session
    today: date
    modules: tuple["Manifest", ...] = ()


@dataclass(frozen=True)
class CardView:
    template: str  # "<module>/card.html", or a core template for core cards
    context: dict = field(default_factory=dict)
    empty: bool = False  # nothing to show: the shell draws the dot-grid page with empty_line
    empty_line: str = ""


@dataclass(frozen=True)
class Card:
    """One card on Home. The shell gives it the card, the tape label, the size and the
    state; the module brings what's inside."""

    id: str  # unique across the app; the layout is saved by this id
    label: str  # the tape label
    color: str  # a palette name (core/palette.py)
    render: Callable[[CardContext], CardView]
    sizes: tuple[str, ...] = ("M",)  # keys of SIZES this card supports
    default_size: str = "M"
    side: bool = False  # playful cards live in Home's side area
    attention: Callable[[CardContext], bool] | None = None  # true: the needs-attention ring
    default_shown: bool = True
    rank: int = 100  # default place on Home and in the rail, lowest first


@dataclass(frozen=True)
class Manifest:
    name: str  # also the package name under brain_dock/modules/ and the template prefix
    description: str
    home: str  # where "/" goes when this is the first enabled module
    router: APIRouter
    paths: tuple[str, ...]  # URL prefixes every route of this module stays under
    nav: tuple[NavEntry, ...]
    tables: tuple[str, ...]  # tables this module owns
    migrations: Path  # this module's Alembic versions folder (its own branch)
    templates: Path  # loaded as "<name>/<file>", so names can't clash across modules
    static: Path | None = None  # served at /static/modules/<name>/
    stylesheets: tuple[str, ...] = ()  # extra stylesheet URLs for every page
    template_globals: dict[str, Callable] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()  # core services it uses; enforced once they exist
    jobs: tuple = ()  # scheduled jobs; none until the scheduler exists
    mcp_tools: tuple = ()  # later
    # Tools its agents may use (ADR 0008); every one must pass core.agents.tools' policy.
    agent_tools: tuple[AgentTool, ...] = ()
    # Its lines for the daily brief (ADR 0013): counts and dates only, never names or free
    # text, because the brief can be read aloud by an outside service. One exception
    # (ADR 0015): to-do titles the owner marked "ok to read aloud".
    brief: Callable[[Session, date], list[str]] | None = None
    # Documented exception (ADR 0007): table names allowed without the module-name prefix.
    legacy_table_names: tuple[str, ...] = ()
    # The shell (ADR 0016).
    label: str = ""  # display name in the rail and on pages (ADR 0012); defaults to name
    color: str = "graphite"  # palette name: its ink dot in the rail
    icon: str = ""  # one SVG path (24x24 viewBox) for the rail
    cards: tuple[Card, ...] = ()
    settings: str | None = None  # an optional settings page path
    off_by_default: bool = False  # its cards start hidden on Home
    # An optional path that accepts a quick note (form field "text"). Home's quick capture
    # and Focus mode's "Park a thought" appear only when an enabled module provides one.
    capture: str | None = None

    @property
    def display_name(self) -> str:
        return self.label or self.name
