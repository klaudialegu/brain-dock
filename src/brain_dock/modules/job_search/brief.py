"""Career Radar's lines for the daily brief (ADR 0013): counts and dates only. No company,
role, note, link or person ever goes in, because the brief can be read aloud by an
outside service."""

from datetime import date

from sqlmodel import Session, select

from brain_dock.modules.job_search.models import Application, Stage
from brain_dock.modules.job_search.stages import STAGES


def count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def brief_lines(session: Session, today: date) -> list[str]:
    rows = session.exec(select(Application.current_stage, Application.follow_up_on)).all()
    open_rows = [(Stage(s), f) for s, f in rows if STAGES[Stage(s)].kind != "closed"]

    lines = []
    overdue = sum(1 for _, f in open_rows if f is not None and f < today)
    due = sum(1 for _, f in open_rows if f == today)
    if due:
        lines.append(f"{count(due, 'follow-up is', 'follow-ups are')} due today.")
    if overdue:
        lines.append(f"{count(overdue, 'follow-up is', 'follow-ups are')} overdue.")

    by_stage: dict[Stage, int] = {}
    for stage, _ in open_rows:
        by_stage[stage] = by_stage.get(stage, 0) + 1
    active = [
        f"{n} {STAGES[s].label.lower()}"
        for s, n in sorted(by_stage.items(), key=lambda item: STAGES[item[0]].order)
        if STAGES[s].kind == "active"
    ]
    if active:
        lines.append(f"In progress: {', '.join(active)}.")
    if offers := by_stage.get(Stage.offer, 0):
        lines.append(f"{count(offers, 'offer is', 'offers are')} open.")
    if saved := by_stage.get(Stage.interested, 0):
        lines.append(f"{count(saved, 'saved job is', 'saved jobs are')} waiting to be applied to.")
    return lines
