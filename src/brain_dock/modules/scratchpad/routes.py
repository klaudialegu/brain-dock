"""Scratchpad pages (ADR 0017): one page at a time on its paper, a pen tray, day tabs.

Plain form posts with CSRF (ADR 0005). Text also saves while typing (static/scratchpad.js
posts the same form); without scripts the Save button does it. Nothing here logs text.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session

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
    set_style,
    set_text,
    text_layer,
)

router = APIRouter()
SAVED_BY_SCRIPT = "x-scratchpad-save"  # the autosave script's header: answer 204, no page


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
) -> HTMLResponse:
    return render_form(
        request,
        "scratchpad/page.html",
        {"text": text_layer(page).content if page else ""},
        errors,
        status_code,
        page=page,
        days=pages_by_day(session),
        pens=list(PENS.values()),
        papers=PAPERS,
        sizes=SIZES,
        today=date.today(),
    )


def safe_next(value: str | None) -> str:
    """Only a path on this app (never another site): where quick capture returns to."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


@router.get("/scratchpad", response_class=HTMLResponse)
def scratchpad(request: Request, session: SessionDep) -> HTMLResponse:
    page = latest(session)
    if page is None:
        return page_view(request, session, None)
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.get("/scratchpad/{page_id}", response_class=HTMLResponse)
def show_page(request: Request, page_id: int, session: SessionDep) -> HTMLResponse:
    return page_view(request, session, load_page(session, page_id))


@router.post("/scratchpad/pages", dependencies=[Depends(verify_csrf)])
def create_page(session: SessionDep):
    page = new_page(session, date.today())
    session.commit()
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.post("/scratchpad/capture", dependencies=[Depends(verify_csrf)])
def capture(request: Request, session: SessionDep, values: FormValues):
    try:
        append_line(session, date.today(), values.get("text", ""))
    except ScratchpadError:
        session.rollback()  # an empty note: nothing to keep, go back quietly
        return RedirectResponse(safe_next(values.get("next")), status_code=303)
    session.commit()
    return RedirectResponse(safe_next(values.get("next")), status_code=303)


@router.post("/scratchpad/{page_id}/text", dependencies=[Depends(verify_csrf)])
def save_text(request: Request, page_id: int, session: SessionDep, values: FormValues):
    page = load_page(session, page_id)
    try:
        set_text(page, values.get("text", ""))
    except ScratchpadError as e:
        session.rollback()
        if request.headers.get(SAVED_BY_SCRIPT):
            return Response(status_code=400)
        return page_view(request, session, page, {"text": str(e)}, 400)
    session.commit()
    if request.headers.get(SAVED_BY_SCRIPT):
        return Response(status_code=204)
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)


@router.post("/scratchpad/{page_id}/style", dependencies=[Depends(verify_csrf)])
def change_style(page_id: int, session: SessionDep, values: FormValues):
    page = load_page(session, page_id)
    try:
        set_style(page, pen=values.get("pen"), paper=values.get("paper"), size=values.get("size"))
    except ScratchpadError:
        raise HTTPException(status_code=400, detail="Bad request") from None
    session.commit()
    return RedirectResponse(f"/scratchpad/{page.id}", status_code=303)
