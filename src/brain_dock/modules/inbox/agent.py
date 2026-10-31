"""The inbox agent, rules only (harness PR 5a). Emails are parsed into roles; each role is a
work item: received -> (rules) ruled | skipped | needs_review, ruled -> pending_approval
(a pending approval for accept_suggestion), then approve() or reject() moves it on (PR 4c).
PR 6 adds a model judge between ruled and pending_approval.

Invariant: every email ends parsed (each of its roles suggested, skipped, decided or in
needs_review) or itself in needs_review. Nothing is dropped silently.
"""

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from brain_dock.core.agents.gateway import NeedsReviewError
from brain_dock.core.agents.run_tables import (
    APPROVED,
    NEEDS_REVIEW,
    PENDING_APPROVAL,
    REJECTED,
    Approval,
    WorkItem,
)
from brain_dock.core.agents.runs import RECEIVED, ItemKey, Items, Runner, RunReport, Workflow
from brain_dock.modules.inbox.config import DEFAULT_PATH, InboxConfig, load_config
from brain_dock.modules.inbox.models import InboxEmail, InboxRole, InboxRoleSource
from brain_dock.modules.inbox.parser import ParsedRole, parse_email
from brain_dock.modules.inbox.roles import natural_key, role_identity
from brain_dock.modules.inbox.rules import REVIEW, SKIP, decide

MODULE = "inbox"
RULED = "ruled"
SKIPPED = "skipped"


def _now() -> datetime:
    return datetime.now(UTC)


def _role(session: Session, item: WorkItem) -> InboxRole:
    return session.exec(select(InboxRole).where(InboxRole.item_key == item.key)).one()


def make_workflow(config: InboxConfig, engine: Engine) -> Workflow:
    def on_received(ctx, item: WorkItem) -> str:
        with Session(engine) as session:
            role = _role(session, item)
            decision = decide(role, config)
            role.status = {SKIP: SKIPPED, REVIEW: NEEDS_REVIEW}.get(decision.outcome, "suggested")
            role.reason = decision.reason
            session.add(role)
            session.commit()
        if decision.outcome == REVIEW:
            raise NeedsReviewError(decision.reason)  # parked with the rule's reason code
        return SKIPPED if decision.outcome == SKIP else RULED

    def on_ruled(ctx, item: WorkItem) -> str:
        with Session(engine) as session:
            role_id = _role(session, item).id
            # A resumed run may reach this step again: never ask twice for the same role.
            asked = session.exec(
                select(Approval).where(Approval.module == MODULE, Approval.item_id == item.id)
            ).first()
        if asked is None:
            result = ctx.dispatcher.call(
                ctx.capability_pass, "accept_suggestion", {"suggestion_id": role_id}, item.id
            )
            if result.approval_id is None:
                raise NeedsReviewError("approval_not_created")
        return PENDING_APPROVAL

    return Workflow(
        module=MODULE,
        transitions={
            RECEIVED: frozenset({RULED, SKIPPED}),
            RULED: frozenset({PENDING_APPROVAL}),
            PENDING_APPROVAL: frozenset({APPROVED, REJECTED}),
        },
        final=frozenset({SKIPPED, APPROVED, REJECTED, NEEDS_REVIEW}),
        waiting=frozenset({PENDING_APPROVAL}),
        steps={RECEIVED: on_received, RULED: on_ruled},
    )


def _email_key(items: Items, raw: str | bytes, message_id: str | None) -> str:
    # No Message-ID (mock emails): a hash of the whole message stands in for it.
    if message_id is None:
        data = raw.encode() if isinstance(raw, str) else raw
        message_id = "sha256:" + hashlib.sha256(data).hexdigest()
    return items.key_for(MODULE, "email:" + message_id).value


def _store_role(session: Session, items: Items, parsed: ParsedRole) -> tuple[InboxRole, ItemKey]:
    identity = role_identity(parsed.company, parsed.title, parsed.location_text, parsed.link)
    item_key = items.key_for(MODULE, natural_key(identity))
    role = session.exec(select(InboxRole).where(InboxRole.item_key == item_key.value)).first()
    if role is None:
        location, salary = parsed.location, parsed.salary
        role = InboxRole(
            item_key=item_key.value,
            company=parsed.company.strip(),
            title=parsed.title.strip(),
            location=parsed.location_text.strip(),
            company_key=identity.company,
            title_key=identity.title,
            location_key=identity.location,
            link_key=identity.link,
            location_kind=location.kind if location else None,
            location_city=location.city if location else None,
            seniority=parsed.seniority,
            salary_min=salary.min if salary else None,
            salary_max=salary.max if salary else None,
            salary_currency=salary.currency if salary else None,
            salary_period=salary.period if salary else None,
            created_at=_now(),
        )
        session.add(role)
        session.flush()
    return role, item_key


def receive_emails(
    engine: Engine, items: Items, raw_emails: Iterable[str | bytes]
) -> list[ItemKey]:
    """Stores each new email (no body) and its roles; returns the roles' work-item keys.
    The same email twice changes nothing; the same role in two emails is one role with
    both emails linked."""
    keys: list[ItemKey] = []
    with Session(engine) as session:
        for raw in raw_emails:
            try:
                parsed = parse_email(raw)
            except Exception:  # noqa: BLE001 (any unreadable email is parked, never dropped)
                parsed = None
            key = _email_key(items, raw, parsed.message_id if parsed else None)
            if session.exec(select(InboxEmail).where(InboxEmail.key == key)).first():
                continue
            mail = InboxEmail(key=key, received_at=_now(), status="parsed")
            if parsed is None or not parsed.roles:
                mail.status = NEEDS_REVIEW
                mail.reason = "unreadable_email" if parsed is None else "no_roles_found"
            session.add(mail)
            session.flush()
            for parsed_role in parsed.roles if parsed else ():
                role, item_key = _store_role(session, items, parsed_role)
                link = session.get(InboxRoleSource, (role.id, mail.id))
                if link is None:
                    session.add(InboxRoleSource(role_id=role.id, email_id=mail.id))
                    mail.role_count += 1
                keys.append(item_key)
            session.commit()
    return keys


def run_inbox(
    runner: Runner, raw_emails: Iterable[str | bytes], *, config_path: Path = DEFAULT_PATH
) -> RunReport:
    """One rules-only run. The config is loaded first: if it's missing or broken, this
    raises ConfigError before any email is received (fail closed)."""
    config = load_config(config_path)
    keys = receive_emails(runner.engine, runner.items, raw_emails)
    run_id = runner.start(MODULE, budget_limit_micro_usd=0)  # rules only: nothing to spend
    return runner.run(make_workflow(config, runner.engine), run_id, keys)
