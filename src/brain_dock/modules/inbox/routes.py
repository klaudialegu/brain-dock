"""Inbox pages (harness PR 5b): the triage page, where I approve or reject each suggestion,
the review page for what the rules set aside, and the rejection log.

Approve and reject go through the core's approvals (exact input, at most once, outside any
agent run). Pages show fixed text and reason codes, never an exception or my thresholds.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, func, select

from brain_dock.core import db
from brain_dock.core.agents.approvals import Approvals
from brain_dock.core.agents.audit import AuditLog, key_path_for, load_or_create_key
from brain_dock.core.agents.passes import default_switch_folder
from brain_dock.core.agents.run_tables import Approval, WorkItem
from brain_dock.core.security import verify_csrf
from brain_dock.core.web import FormValues, SessionDep, render, render_form
from brain_dock.modules.inbox import config
from brain_dock.modules.inbox.models import InboxEmail, InboxRole, InboxRoleSource

router = APIRouter()

ROLE_LABELS = {
    "new": "Not ruled yet",
    "suggested": "Suggested",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "skipped": "Skipped by rules",
    "needs_review": "Needs review",
}
# What I can say when I reject a suggestion: short codes, never free text (approvals).
REJECT_REASONS = {
    "not_a_fit": "Not a fit",
    "wrong_location": "Wrong location",
    "wrong_level": "Wrong level",
    "pay_too_low": "Pay too low",
    "duplicate": "Duplicate",
}
REASON_LABELS = {
    **REJECT_REASONS,
    "location_mismatch": "Location isn't on my list",
    "seniority_mismatch": "Level isn't on my list",
    "salary_below_floor": "Top of the range is below my floor",
    "missing_salary": "No salary given",
    "missing_location": "No location given",
    "missing_seniority": "No level in the title",
    "salary_no_top": "Salary has no top",
    "salary_other_currency": "Salary in another currency",
    "salary_not_annual": "Salary isn't yearly",
    "no_roles_found": "No roles found in the email",
    "unreadable_email": "The email couldn't be read",
    "tool_error": "The approved change failed",
    "input_changed": "The approval changed after it was made",
    "interrupted": "Cut off while running",
}
# Fixed messages after a decision (post/redirect/get), chosen by a short code.
NOTICES = {
    "approved": "Accepted. Save it as a job from the Accepted list below.",
    "rejected": "Rejected.",
    "refused": "That suggestion couldn't be decided. It may already be decided, or agents "
    "are switched off or running.",
}
PERIOD_LABELS = {"year": "year", "month": "month", "hour": "hour"}


def salary_text(role: InboxRole) -> str:
    if role.salary_currency is None:
        return "Not given"
    low = f"{role.salary_min:,}" if role.salary_min is not None else None
    high = f"{role.salary_max:,}" if role.salary_max is not None else None
    if low and high and low != high:
        amount = f"{low}–{high}"
    elif high:
        amount = high if low else f"up to {high}"
    else:
        amount = f"from {low}"
    return f"{role.salary_currency} {amount} / {PERIOD_LABELS.get(role.salary_period, '?')}"


def approvals_for(request: Request) -> Approvals:
    engine = request.app.state.engine
    audit = AuditLog(engine, load_or_create_key(key_path_for(db.DB_PATH)))
    return Approvals(engine, audit, request.app.state.modules, default_switch_folder)


def config_problem() -> str | None:
    """Why the rules can't run, naming keys only; None when the config is fine. Read on
    each page load, so fixing config.toml shows up without a restart."""
    try:
        config.load_config(config.DEFAULT_PATH)
    except config.ConfigError as e:
        return str(e)
    return None


def pending(session: Session) -> list[tuple[Approval, InboxRole, int]]:
    sources = (
        select(InboxRoleSource.role_id, func.count().label("n"))
        .group_by(InboxRoleSource.role_id)
        .subquery()
    )
    rows = session.exec(
        select(Approval, InboxRole, sources.c.n)
        .join(WorkItem, WorkItem.id == Approval.item_id)
        .join(InboxRole, InboxRole.item_key == WorkItem.key)
        .join(sources, sources.c.role_id == InboxRole.id)
        .where(Approval.module == "inbox", Approval.status == "pending")
        .order_by(Approval.id)
    )
    return list(rows.all())


def rejection_log(session: Session) -> list[tuple[str, str, int]]:
    """(source, reason code, count): my rejections and the rules' skips, side by side, so a
    skipped role never disappears."""
    mine = session.exec(
        select(Approval.reason, func.count())
        .where(Approval.module == "inbox", Approval.status == "rejected")
        .group_by(Approval.reason)
    ).all()
    rules = session.exec(
        select(InboxRole.reason, func.count())
        .where(InboxRole.status == "skipped")
        .group_by(InboxRole.reason)
    ).all()
    rows = [("Me", r, n) for r, n in mine] + [("Rules", r, n) for r, n in rules]
    return sorted(rows, key=lambda row: (row[0], -row[2], row[1]))


def save_link(role: InboxRole) -> str:
    """Job search's save-a-job form, prefilled (ADR 0011): a plain URL, not an import, so
    the module boundary holds. Option A (a core-brokered handoff) would replace it."""
    fields = {"company": role.company, "role_title": role.title}
    if role.link_key:
        fields["link"] = role.link_key
    return "/applications/saved/new?" + urlencode(fields)


def role_counts(session: Session) -> dict[str, int]:
    """Roles by status. Rejecting never runs a tool, so a rejected role still says
    "suggested" in its own row; its work item holds the decision (PR 4c)."""
    rows = session.exec(
        select(InboxRole.status, WorkItem.state)
        .join(WorkItem, WorkItem.key == InboxRole.item_key, isouter=True)
        .where((WorkItem.module == "inbox") | (WorkItem.id.is_(None)))
    ).all()
    counts: dict[str, int] = {}
    for status, state in rows:
        shown = "rejected" if state == "rejected" else status
        counts[shown] = counts.get(shown, 0) + 1
    return counts


@router.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, session: SessionDep, done: str | None = None) -> HTMLResponse:
    by_status = role_counts(session)
    emails = session.exec(select(func.count()).select_from(InboxEmail)).one()
    accepted = session.exec(
        select(InboxRole).where(InboxRole.status == "accepted").order_by(InboxRole.id.desc())
    ).all()
    # Only link to job search while it's enabled; otherwise the link would be a 404.
    can_save = any(m.name == "job_search" for m in request.app.state.modules)
    return render_form(
        request,
        "inbox/index.html",
        {},
        pending=pending(session),
        accepted=accepted,
        save_link=save_link if can_save else None,
        counts=[(label, by_status.get(status, 0)) for status, label in ROLE_LABELS.items()],
        emails=emails,
        log=rejection_log(session),
        config_problem=config_problem(),
        notice=NOTICES.get(done or ""),
        reject_reasons=REJECT_REASONS,
        reason_labels=REASON_LABELS,
        salary_text=salary_text,
    )


@router.get("/inbox/review", response_class=HTMLResponse)
def review(request: Request, session: SessionDep) -> HTMLResponse:
    roles = session.exec(
        select(InboxRole).where(InboxRole.status == "needs_review").order_by(InboxRole.id)
    ).all()
    emails = session.exec(
        select(InboxEmail).where(InboxEmail.status == "needs_review").order_by(InboxEmail.id)
    ).all()
    context = {"roles": roles, "emails": emails, "reason_labels": REASON_LABELS}
    return render(request, "inbox/review.html", context)


def inbox_approval(session: Session, approval_id: int) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None or approval.module != "inbox":  # this page decides inbox ones only
        raise HTTPException(status_code=404, detail="Not found")
    return approval


@router.post("/inbox/approvals/{approval_id}/approve", dependencies=[Depends(verify_csrf)])
def approve(request: Request, approval_id: int, session: SessionDep):
    inbox_approval(session, approval_id)
    result = approvals_for(request).approve(approval_id)
    # Post/redirect/get: refreshing can't decide twice (and approve refuses anyway).
    return RedirectResponse(f"/inbox?done={'approved' if result.ok else 'refused'}", 303)


@router.post("/inbox/approvals/{approval_id}/reject", dependencies=[Depends(verify_csrf)])
def reject(request: Request, approval_id: int, session: SessionDep, values: FormValues):
    inbox_approval(session, approval_id)
    reason = values.get("reason", "")
    if reason not in REJECT_REASONS:
        raise HTTPException(status_code=400, detail="Bad request")
    result = approvals_for(request).reject(approval_id, reason)
    return RedirectResponse(f"/inbox?done={'rejected' if result.ok else 'refused'}", 303)
