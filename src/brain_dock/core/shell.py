"""The shell (ADR 0016): the rail, Home, Settings, and the Brief page and card.

Every page gets the rail from `shell_state`, an app-wide dependency, so the rail follows
the saved layout. Home draws each shown card the same way: the module brings what's
inside; the shell gives the card, the tape label, the size and one of three states.
"""

from dataclasses import dataclass
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from brain_dock.core import layout
from brain_dock.core.brief import NOTHING, lines_by_module
from brain_dock.core.modules import Card, CardContext, CardView
from brain_dock.core.palette import PALETTE, palette_css
from brain_dock.core.security import verify_csrf
from brain_dock.core.web import FormValues, SessionDep, render, render_form

router = APIRouter()

HOME_ICON = "M4 11 12 4l8 7v9h-5v-6H9v6H4z"
BRIEF_ICON = "M5 6h14M5 11h10M5 16h7"
SETTINGS_ICON = "M5 7h14M5 12h14M5 17h14M9 5v4M15 10v4M8 15v4"


def brief_card(ctx: CardContext) -> CardView:
    lines = [
        line for ls in lines_by_module(ctx.session, ctx.today, ctx.modules).values() for line in ls
    ]
    return CardView("brief_card.html", {"lines": lines}, empty=not lines, empty_line=NOTHING)


BRIEF = Card(
    id="brief",
    label="Brief",
    color="lavender",
    render=brief_card,
    sizes=("M", "L"),
    default_size="M",
    rank=20,
)
CORE_CARDS = (BRIEF,)


@dataclass(frozen=True)
class RailEntry:
    label: str
    path: str
    icon: str
    color: str
    current: bool


def _current(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def rail(request: Request, session) -> list[RailEntry]:
    """Home, then the core's and the shown modules' entries in layout order."""
    modules = request.app.state.modules
    path = request.url.path
    entries, seen = [], set()
    for placed in layout.layout(session, modules, CORE_CARDS):
        if not placed.shown:
            continue
        if placed.module is None:
            key, entry = (
                placed.card.id,
                RailEntry(
                    placed.card.label,
                    "/brief",
                    BRIEF_ICON,
                    placed.card.color,
                    _current(path, ("/brief",)),
                ),
            )
        else:
            m = placed.module
            key, entry = (
                m.name,
                RailEntry(
                    m.display_name, m.home, m.icon or BRIEF_ICON, m.color, _current(path, m.paths)
                ),
            )
        if key not in seen:
            seen.add(key)
            entries.append(entry)
    return entries


def shell_state(request: Request, session: SessionDep) -> None:
    """Runs for every route (an app-wide dependency), so each page gets its rail."""
    request.state.shell = {
        "rail": rail(request, session),
        "highlighter": layout.highlighter(session),
        "capture": next(
            (
                m.capture
                for m in layout.visible_modules(session, request.app.state.modules, CORE_CARDS)
                if m.capture
            ),
            None,
        ),
    }


def page_module(request: Request):
    """The module whose pages this is, for its sub-nav."""
    for m in request.app.state.modules:
        if _current(request.url.path, m.paths):
            return m
    return None


def _state(card: Card, view: CardView, ctx: CardContext) -> str:
    if view.empty:
        return "empty"
    if card.attention is not None and card.attention(ctx):
        return "attention"
    return "calm"


def greeting_word(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    return "Good afternoon" if now.hour < 18 else "Good evening"


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: SessionDep) -> HTMLResponse:
    modules = request.app.state.modules
    today = date.today()
    ctx = CardContext(
        session=session,
        today=today,
        modules=tuple(layout.visible_modules(session, modules, CORE_CARDS)),
    )
    main, side = [], []
    for placed in layout.layout(session, modules, CORE_CARDS):
        if not placed.shown:
            continue
        view = placed.card.render(ctx)
        item = {
            "card": placed.card,
            "size": placed.size,
            "view": view,
            "state": _state(placed.card, view, ctx),
        }
        (side if placed.card.side else main).append(item)
    # A form page: quick capture posts with the CSRF token (when a module accepts notes).
    return render_form(
        request,
        "home.html",
        {},
        cards=main,
        side_cards=side,
        today=today,
        greeting=greeting_word(datetime.now()),
        no_modules=not modules,
    )


@router.get("/brief", response_class=HTMLResponse)
def brief_page(request: Request, session: SessionDep) -> HTMLResponse:
    today = date.today()
    by_module = lines_by_module(session, today, request.app.state.modules)
    lines = [line for ls in by_module.values() for line in ls]
    return render(request, "brief.html", {"lines": lines, "today": today, "nothing": NOTHING})


@router.get("/palette.css")
def palette_stylesheet() -> Response:
    return Response(palette_css(), media_type="text/css")


def settings_page(
    request: Request, session, errors: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    placed = layout.layout(session, request.app.state.modules, CORE_CARDS)
    return render_form(
        request,
        "settings.html",
        {"highlighter": layout.highlighter(session)},
        errors,
        status_code,
        placed=placed,
        palette=list(PALETTE.values()),
    )


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request, session: SessionDep) -> HTMLResponse:
    return settings_page(request, session)


def _change(request: Request, session, action) -> RedirectResponse:
    try:
        action(session, request.app.state.modules)
    except layout.LayoutError:
        raise HTTPException(status_code=400, detail="Bad request") from None
    session.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/cards/{card_id}/shown", dependencies=[Depends(verify_csrf)])
def card_shown(request: Request, card_id: str, session: SessionDep, values: FormValues):
    shown = values.get("shown") == "1"
    return _change(
        request, session, lambda s, ms: layout.set_shown(s, ms, card_id, shown, CORE_CARDS)
    )


@router.post("/settings/cards/{card_id}/move", dependencies=[Depends(verify_csrf)])
def card_move(request: Request, card_id: str, session: SessionDep, values: FormValues):
    direction = {"up": -1, "down": 1}.get(values.get("direction", ""))
    if direction is None:
        raise HTTPException(status_code=400, detail="Bad request")
    return _change(
        request, session, lambda s, ms: layout.move(s, ms, card_id, direction, CORE_CARDS)
    )


@router.post("/settings/cards/{card_id}/size", dependencies=[Depends(verify_csrf)])
def card_size(request: Request, card_id: str, session: SessionDep, values: FormValues):
    size = values.get("size", "")
    return _change(
        request, session, lambda s, ms: layout.set_size(s, ms, card_id, size, CORE_CARDS)
    )


@router.post("/settings/highlighter", dependencies=[Depends(verify_csrf)])
def choose_highlighter(request: Request, session: SessionDep, values: FormValues):
    return _change(
        request, session, lambda s, ms: layout.set_highlighter(s, values.get("highlighter", ""))
    )
