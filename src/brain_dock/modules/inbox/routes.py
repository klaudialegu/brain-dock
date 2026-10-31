"""Inbox pages. For now (PR 5a) one status page with counts only; the triage page with
approve and reject replaces it at the same path in PR 5b."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlmodel import func, select

from brain_dock.core.web import SessionDep, render
from brain_dock.modules.inbox.models import InboxEmail, InboxRole

router = APIRouter()

ROLE_LABELS = {
    "new": "Not ruled yet",
    "suggested": "Suggested",
    "accepted": "Accepted",
    "skipped": "Skipped by rules",
    "needs_review": "Needs review",
}


@router.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, session: SessionDep) -> HTMLResponse:
    by_status = dict(
        session.exec(select(InboxRole.status, func.count()).group_by(InboxRole.status)).all()
    )
    counts = [(label, by_status.get(status, 0)) for status, label in ROLE_LABELS.items()]
    emails = session.exec(select(func.count()).select_from(InboxEmail)).one()
    emails_parked = session.exec(
        select(func.count()).select_from(InboxEmail).where(InboxEmail.status == "needs_review")
    ).one()
    context = {"counts": counts, "emails": emails, "emails_parked": emails_parked}
    return render(request, "inbox/index.html", context)
