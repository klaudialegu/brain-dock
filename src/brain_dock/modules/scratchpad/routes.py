"""Scratchpad pages (ADR 0017): one page at a time on its paper, a pen tray, day tabs.

Plain form posts with CSRF (ADR 0005). Text also saves while typing (static/scratchpad.js
posts the same form); without scripts the Save button does it. Nothing here logs text.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

from brain_dock.core.flash import read_message, set_message
from brain_dock.core.security import verify_csrf
from brain_dock.core.web import FormValues, SessionDep, render_form
from brain_dock.modules.scratchpad.models import (
    PAPERS,
    PENS,
    SIZES,
    ScratchpadError,
    ScratchpadPage,
    append_line,
    latest,
    new_page,
    pages_by_day,
    remove_page,
    restore_page,
    revision,
    set_style,
    set_text,
    text_layer,
    with_new_lines,
)

router = APIRouter()
SAVED_BY_SCRIPT = "x-scratchpad-save"  # the autosave script's header: answer 204, no page
CAPTURED_BY_SCRIPT = "x-scratchpad-capture"  # a page's own capture script: 204, no redirect


def load_page(session: Session, page_id: int) -> ScratchpadPage:
    page = session.get(ScratchpadPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return page


def page_view(
    request: Request,
    session: Session,
    page: ScratchpadPage | None,
    errors: dict | None = None,
    status_code: int = 200,
    text: str | None = None,
    saved: str | None = None,
) -> HTMLResponse:
    """`text` keeps what was typed when a save is refused, so nothing typed is lost; `saved`
    shows the page as stored when it changed elsewhere."""
    return render_form(
        request,
        "scratchpad/page.html",
        {"text": text if text is not None else (text_layer(page).content if page else "")},
        errors,
        status_code,
        page=page,
        days=pages_by_day(session),
        pens=list(PENS.values()),
        papers=PAPERS,
        sizes=SIZES,
        today=date.today(),
        base=revision(page) if page else "",
        saved=saved,
        message_bar=message_bar(request, session),
    )


def page_label(page: ScratchpadPage) -> str:
    label = f"{page.day:%a %b} {page.day.day}"
    return f"{label} · page {page.position}" if page.position > 1 else label


def message_bar(request: Request, session: Session) -> dict | None:
    """The one-time "Removed: … · Undo" bar, if the last action left one."""
    waiting = read_message(request)
    if waiting is None or waiting[0] != "page_removed" or waiting[1] is None:
        return None
    page = session.get(ScratchpadPage, waiting[1])
    if page is None or page.removed_at is None:
        return None
    return {"text": f"Removed page: {page_label(page)}", "undo": f"/scratchpad/{page.id}/restore"}


def removed_view(request: Request, page: ScratchpadPage, typed: str = "") -> HTMLResponse:
    """A removed page opened or changed (Back, an old tab): say so, offer Undo, no editor,
    and show anything that was just typed so it isn't lost."""
    return render_form(
        request,
        "scratchpad/removed.html",
        {},
        None,
        410,
        page=page,
        label=page_label(page),
        typed=typed,
    )


@router.get("/scratchpad", response_class=HTMLResponse)
def scratchpad(request: Request, session: SessionDep) -> HTMLResponse:
    page = latest(session)
    if page is None:
        return page_view(request, session, None)
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.get("/scratchpad/{page_id}", response_class=HTMLResponse)
def show_page(request: Request, page_id: int, session: SessionDep) -> HTMLResponse:
    page = load_page(session, page_id)
    if page.removed_at is not None:
        return removed_view(request, page)
    return page_view(request, session, page)


@router.post("/scratchpad/pages", dependencies=[Depends(verify_csrf)])
def create_page(session: SessionDep):
    page = new_page(session, date.today())
    session.commit()
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.post("/scratchpad/capture", dependencies=[Depends(verify_csrf)])
def capture(request: Request, session: SessionDep, values: FormValues):
    """One line on today's page. The form on Home comes back to Home; a page's own script
    (Focus mode's "Park a thought") gets 204 and stays where it is. The destination never
    comes from the request, so this can't be turned into a redirect to another site."""
    text = values.get("text", "")
    try:
        append_line(session, date.today(), text)
    except ScratchpadError:
        session.rollback()
        if text.strip():  # too long: say so rather than drop it (the field caps it first)
            raise HTTPException(status_code=400, detail="Note too long") from None
        # an empty note: nothing to keep
    else:
        session.commit()
    if request.headers.get(CAPTURED_BY_SCRIPT):
        return Response(status_code=204)
    return RedirectResponse("/", status_code=303)


@router.post("/scratchpad/{page_id}/text", dependencies=[Depends(verify_csrf)])
def save_text(request: Request, page_id: int, session: SessionDep, values: FormValues):
    page = load_page(session, page_id)
    text = values.get("text", "")
    by_script = bool(request.headers.get(SAVED_BY_SCRIPT))
    if page.removed_at is not None:  # removed in another tab: keep what was typed
        return Response(status_code=410) if by_script else removed_view(request, page, text)
    if values.get("base", "") != revision(page):  # changed since this form loaded
        if by_script:
            return Response(status_code=409)
        saved = text_layer(page).content
        message = (
            "Text: this page changed since you opened it. Lines added elsewhere (a quick "
            "note, say) are now at the end of your text. Check it, then Save."
        )
        return page_view(
            request, session, page, {"text": message}, 409, with_new_lines(text, saved), saved
        )
    try:
        set_text(page, text)
    except ScratchpadError as e:
        session.rollback()
        if by_script:
            return Response(status_code=400)
        return page_view(request, session, page, {"text": str(e)}, 400, text)
    session.commit()
    if by_script:  # the script keeps its base current from this header
        return Response(status_code=204, headers={"x-scratchpad-base": revision(page)})
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.post("/scratchpad/{page_id}/style", dependencies=[Depends(verify_csrf)])
def change_style(request: Request, page_id: int, session: SessionDep, values: FormValues):
    page = load_page(session, page_id)
    if page.removed_at is not None:
        return removed_view(request, page)
    try:
        set_style(page, pen=values.get("pen"), paper=values.get("paper"), size=values.get("size"))
    except ScratchpadError:
        raise HTTPException(status_code=400, detail="Bad request") from None
    session.commit()
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.post("/scratchpad/{page_id}/remove", dependencies=[Depends(verify_csrf)])
def remove(request: Request, page_id: int, session: SessionDep):
    page = load_page(session, page_id)
    if page.removed_at is not None:
        return removed_view(request, page)
    remove_page(page)
    session.commit()
    response = RedirectResponse("/scratchpad", status_code=303)
    set_message(response, "page_removed", page.id)
    return response


@router.post("/scratchpad/{page_id}/restore", dependencies=[Depends(verify_csrf)])
def restore(request: Request, page_id: int, session: SessionDep, values: FormValues):
    """Undo. From "This page was removed" the form also carries what was typed in the old
    tab: it's kept, merged like a refused save (the typed text, then any saved line it
    lacks), so Undo never loses those words either."""
    page = load_page(session, page_id)
    try:
        restore_page(page)
    except ScratchpadError:
        return Response("Nothing to undo", status_code=409)  # a live page: nothing changes
    typed = values.get("typed", "")
    if typed.strip():
        merged = with_new_lines(typed, text_layer(page).content)
        try:
            set_text(page, merged)
        except ScratchpadError as e:  # too long to keep: the page is back, the words on screen
            session.commit()
            return page_view(request, session, page, {"text": str(e)}, 400, merged)
    session.commit()
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)
