"""The inbox's line for the daily brief (ADR 0013): a count only, never a company or role."""

from datetime import date

from sqlmodel import Session, func, select

from brain_dock.core.agents.run_tables import Approval


def brief_lines(session: Session, today: date) -> list[str]:
    waiting = session.exec(
        select(func.count())
        .select_from(Approval)
        .where(Approval.module == "inbox", Approval.status == "pending")
    ).one()
    if not waiting:
        return []
    noun = "role is" if waiting == 1 else "roles are"
    return [f"{waiting} inbox {noun} waiting for your decision."]
