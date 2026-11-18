"""To do: tasks for today and later, with optional ordered steps (ADR 0015).

Titles are personal data: they stay in the local database, never in logs or errors, and
reach the morning brief only when a task is marked "ok to read aloud" (off by default).
"""

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Literal

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, Session, SQLModel, select

Bucket = Literal["today", "can_wait"]
BUCKETS: tuple[str, ...] = ("today", "can_wait")
TITLE_MAX = 200
MINUTES_MAX = 1440  # a day


class TodoTask(SQLModel, table=True):
    __tablename__ = "todo_task"

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=TITLE_MAX)
    due_on: date | None = None
    done: bool = False
    done_at: datetime | None = None  # UTC; compared as a local date (see done_on)
    ok_to_read_aloud: bool = False  # off by default: a title is read aloud only when on
    estimate_minutes: int | None = None
    bucket: str = "today"  # one of BUCKETS
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    steps: list["TodoStep"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "TodoStep.position"},
    )


class TodoStep(SQLModel, table=True):
    __tablename__ = "todo_step"
    __table_args__ = (UniqueConstraint("task_id", "position", name="uq_todo_step_position"),)

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="todo_task.id", index=True, ondelete="CASCADE")
    position: int  # 1, 2, 3… within its task
    title: str = Field(max_length=TITLE_MAX)
    minutes: int | None = None
    done: bool = False

    task: TodoTask | None = Relationship(back_populates="steps")


class TodoFieldError(ValueError):
    """A field is out of range. The message names the field, never the value."""


def _check(title: str, minutes: int | None, minutes_label: str) -> str:
    title = title.strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise TodoFieldError(f"Title: 1 to {TITLE_MAX} characters")
    if minutes is not None and not 1 <= minutes <= MINUTES_MAX:
        raise TodoFieldError(f"{minutes_label}: 1 to {MINUTES_MAX} minutes")
    return title


def add_task(
    session: Session,
    title: str,
    *,
    bucket: str = "today",
    due_on: date | None = None,
    estimate_minutes: int | None = None,
    ok_to_read_aloud: bool = False,
) -> TodoTask:
    """A new task. The caller commits."""
    task = TodoTask(title="-")
    update_task(task, title, bucket, due_on, estimate_minutes, ok_to_read_aloud)
    session.add(task)
    return task


def update_task(
    task: TodoTask,
    title: str,
    bucket: str,
    due_on: date | None,
    estimate_minutes: int | None,
    ok_to_read_aloud: bool,
) -> None:
    if bucket not in BUCKETS:
        raise TodoFieldError("Bucket: Today or Can wait")
    task.title = _check(title, estimate_minutes, "Estimate")
    task.bucket, task.due_on = bucket, due_on
    task.estimate_minutes, task.ok_to_read_aloud = estimate_minutes, ok_to_read_aloud


def set_done(task: TodoTask, done: bool, now: datetime | None = None) -> None:
    task.done = done
    task.done_at = (now or datetime.now(UTC)) if done else None


def move_to(task: TodoTask, bucket: str) -> None:
    if bucket not in BUCKETS:
        raise TodoFieldError("Bucket: Today or Can wait")
    task.bucket = bucket


def add_step(session: Session, task: TodoTask, title: str, minutes: int | None) -> TodoStep:
    step = TodoStep(
        title=_check(title, minutes, "Minutes"), minutes=minutes, position=len(task.steps) + 1
    )
    task.steps.append(step)
    session.add(step)
    return step


def move_step(session: Session, task: TodoTask, step: TodoStep, direction: int) -> None:
    """Swap with the step above (-1) or below (+1). Positions are unique per task, so the
    swap goes through a free position first."""
    other_position = step.position + direction
    other = next((s for s in task.steps if s.position == other_position), None)
    if other is None:
        return
    old = step.position
    step.position = 0
    session.flush()
    other.position = old
    session.flush()
    step.position = other_position
    session.flush()


def remove_step(session: Session, task: TodoTask, step: TodoStep) -> None:
    """Remove a step; the ones after it move up, so positions stay 1, 2, 3…"""
    removed = step.position
    task.steps.remove(step)
    session.flush()
    for later in sorted(task.steps, key=lambda s: s.position):
        if later.position > removed:
            later.position -= 1
            session.flush()


def local_zone() -> tzinfo:
    return datetime.now().astimezone().tzinfo


def done_on(task: TodoTask, zone: tzinfo | None = None) -> date | None:
    """The local day a task was done. Stored in UTC: a task finished at 9 pm here counts
    on that day here, not the next day in UTC."""
    if task.done_at is None:
        return None
    moment = task.done_at if task.done_at.tzinfo else task.done_at.replace(tzinfo=UTC)
    return moment.astimezone(zone or local_zone()).date()


def is_for_today(task: TodoTask, today: date) -> bool:
    """In Today, or due today or earlier, wherever it sits."""
    return task.bucket == "today" or (task.due_on is not None and task.due_on <= today)


def todays_open(session: Session, today: date) -> list[TodoTask]:
    tasks = session.exec(select(TodoTask).where(TodoTask.done == False)).all()  # noqa: E712
    return sorted((t for t in tasks if is_for_today(t, today)), key=_order)


def card(
    session: Session, today: date, zone: tzinfo | None = None
) -> tuple[list[TodoTask], list[TodoTask]]:
    """(Today, Can wait). Today: open tasks for today, plus ones done today (local date),
    in place. Older done tasks drop off. Can wait: the rest that's open."""
    tasks = session.exec(select(TodoTask)).all()
    today_list = [
        t for t in tasks if is_for_today(t, today) and (not t.done or done_on(t, zone) == today)
    ]
    can_wait = [t for t in tasks if not t.done and not is_for_today(t, today)]
    return sorted(today_list, key=_order), sorted(can_wait, key=_order)


def _order(task: TodoTask):
    return (task.due_on is None, task.due_on or date.max, task.id or 0)


def total_minutes(task: TodoTask) -> int | None:
    """The estimate, or the steps' minutes added up when there's no estimate."""
    if task.estimate_minutes:
        return task.estimate_minutes
    return sum(s.minutes for s in task.steps if s.minutes) or None


def when_label(due_on: date | None, today: date) -> str:
    """A loose "when" for Can wait."""
    if due_on is None:
        return "someday"
    end_of_week = today + timedelta(days=6 - today.weekday())  # Sunday
    if due_on <= end_of_week:
        return "this week"
    return f"by {due_on:%b} {due_on.day}"


def meta(task: TodoTask, today: date) -> str:
    """ "~45 min · due Fri" for the card."""
    parts = []
    if minutes := total_minutes(task):
        parts.append(f"~{minutes} min")
    if task.due_on is not None and not task.done:
        if task.due_on < today:
            parts.append("overdue")
        elif task.due_on == today:
            parts.append("due today")
        elif task.due_on <= today + timedelta(days=6):
            parts.append(f"due {task.due_on:%a}")
        else:
            parts.append(f"due {task.due_on:%b} {task.due_on.day}")
    return " · ".join(parts)
