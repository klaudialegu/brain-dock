"""To-do pages: the card (Today and Can wait) with an add form, and the edit page with steps.

Plain form posts with CSRF (ADR 0005), no scripts. Nothing here logs a title.
Remove keeps the task or step for Undo (ADR 0018). A removed task refuses every change
(say, from a page left open in another tab) with a page that offers Undo, never a bare 404.
"""

import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session

from brain_dock.core.flash import read_message, set_message
from brain_dock.core.security import verify_csrf
from brain_dock.core.web import FormValues, SessionDep, render_form
from brain_dock.modules.todo.models import (
    TodoFieldError,
    TodoStateError,
    TodoStep,
    TodoTask,
    add_step,
    add_task,
    card,
    current_step,
    done_on,
    done_recently,
    focus_minutes,
    live_steps,
    meta,
    move_step,
    move_to,
    remove_step,
    remove_task,
    restore_step,
    restore_task,
    set_done,
    total_minutes,
    update_task,
    when_label,
)
from brain_dock.modules.todo.schemas import StepForm, TaskForm, form_errors

router = APIRouter()
BUCKET_OPTIONS = [("today", "Today"), ("can_wait", "Can wait")]


def message_bar(request: Request, session: Session) -> dict | None:
    """The one-time "Removed: … · Undo" bar, if the last action left one."""
    waiting = read_message(request)
    if waiting is None or waiting[1] is None:
        return None
    kind, item_id = waiting
    if kind == "task_removed":
        task = session.get(TodoTask, item_id)
        if task is not None and task.removed_at is not None:
            return {"text": f"Removed: {task.title}", "undo": f"/todo/{task.id}/restore"}
    if kind == "step_removed":
        step = session.get(TodoStep, item_id)
        if step is not None and step.removed_at is not None:
            return {
                "text": f"Removed step: {step.title}",
                "undo": f"/todo/{step.task_id}/steps/{step.id}/restore",
            }
    return None


def page(
    request: Request,
    session: Session,
    values: dict | None = None,
    errors: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    today = date.today()
    today_list, can_wait = card(session, today)
    return render_form(
        request,
        "todo/index.html",
        values or {},
        errors,
        status_code,
        today_list=[(t, meta(t, today)) for t in today_list],
        can_wait=[(t, when_label(t.due_on, today)) for t in can_wait],
        open_count=sum(1 for t in today_list if not t.done),
        done_recently=[(t, when_done(t, today)) for t in done_recently(session, today)],
        bucket_options=BUCKET_OPTIONS,
        message_bar=message_bar(request, session),
    )


def when_done(task: TodoTask, today: date) -> str:
    day = done_on(task)
    if day == today:
        return "done today"
    if day == today - timedelta(days=1):
        return "done yesterday"
    return f"done {day:%a}" if day else ""


def removed_page(
    request: Request, task: TodoTask, values: dict | None = None, status_code: int = 410
) -> HTMLResponse:
    """A removed task asked for or changed (an old tab, Back): say so, offer Undo, and
    show anything that was just typed so it isn't lost."""
    typed = {k: v for k, v in (values or {}).items() if k in TYPED_FIELDS and v.strip()}
    return render_form(request, "todo/removed.html", {}, None, status_code, task=task, typed=typed)


TYPED_FIELDS = ("title", "due_on", "estimate_minutes", "minutes")


def load_task(session: Session, task_id: int) -> TodoTask:
    task = session.get(TodoTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    return task


def load_step(task: TodoTask, step_id: int) -> TodoStep:
    """Any step of the task, removed or not; callers that change it check first."""
    step = next((s for s in task.steps if s.id == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail="Not found")
    return step


def step_gone(request: Request, task: TodoTask, step: TodoStep) -> HTMLResponse:
    """A removed step was changed (an old tab): the edit page, saying so, with Undo."""
    return edit_page(
        request,
        task,
        status_code=410,
        bar={
            "text": f"This step was removed: {step.title}",
            "undo": f"/todo/{task.id}/steps/{step.id}/restore",
            "close": f"/todo/{task.id}/edit",  # this page answers a POST: × goes here
        },
    )


def task_values(task: TodoTask) -> dict:
    return {
        "title": task.title,
        "bucket": task.bucket,
        "due_on": task.due_on.isoformat() if task.due_on else "",
        "estimate_minutes": str(task.estimate_minutes or ""),
        "ok_to_read_aloud": "on" if task.ok_to_read_aloud else "",
    }


def edit_page(
    request: Request,
    task: TodoTask,
    values: dict | None = None,
    errors: dict | None = None,
    step_errors: dict | None = None,
    step_values: dict | None = None,
    status_code: int = 200,
    bar: dict | None = None,
) -> HTMLResponse:
    return render_form(
        request,
        "todo/edit.html",
        values if values is not None else task_values(task),
        errors,
        status_code,
        task=task,
        steps=live_steps(task),
        total=total_minutes(task),
        step_values=step_values or {},
        step_errors=step_errors or {},
        bucket_options=BUCKET_OPTIONS,
        message_bar=bar or message_bar(request, session_of(task)),
    )


def session_of(task: TodoTask) -> Session:
    return Session.object_session(task)


def back_to_list() -> RedirectResponse:
    return RedirectResponse("/todo", status_code=303)


def back_to_edit(task: TodoTask) -> RedirectResponse:
    return RedirectResponse(f"/todo/{task.id}/edit", status_code=303)


def go_back(values: dict, task: TodoTask, default: RedirectResponse) -> RedirectResponse:
    """Where a form on Home's card or in Focus mode returns. A fixed word picks the page;
    an address is never taken from the request, so this can't redirect to another site."""
    where = values.get("back")
    if where == "home":
        return RedirectResponse("/", status_code=303)
    if where == "focus":
        return RedirectResponse(f"/todo/{task.id}/focus", status_code=303)
    return default


@router.get("/todo", response_class=HTMLResponse)
def todo(request: Request, session: SessionDep) -> HTMLResponse:
    return page(request, session)


@router.post("/todo", dependencies=[Depends(verify_csrf)])
def create_task(request: Request, session: SessionDep, values: FormValues):
    try:
        entry = TaskForm.model_validate(values)
    except ValidationError as e:
        return page(request, session, values, form_errors(e), 400)
    add_task(
        session,
        entry.title,
        bucket=entry.bucket,
        due_on=entry.due_on,
        estimate_minutes=entry.estimate_minutes,
        ok_to_read_aloud=entry.ok_to_read_aloud,
    )
    session.commit()
    return back_to_list()


@router.post("/todo/{task_id}/done", dependencies=[Depends(verify_csrf)])
def mark_done(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    set_done(task, values.get("done") == "1")
    session.commit()
    return go_back(values, task, back_to_list())


@router.post("/todo/{task_id}/bucket", dependencies=[Depends(verify_csrf)])
def change_bucket(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    try:
        move_to(task, values.get("bucket", ""))
    except TodoFieldError:
        raise HTTPException(status_code=400, detail="Bad request") from None
    session.commit()
    return go_back(values, task, back_to_list())


@router.get("/todo/{task_id}/edit", response_class=HTMLResponse)
def edit_task(request: Request, task_id: int, session: SessionDep) -> HTMLResponse:
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    return edit_page(request, task)


@router.post("/todo/{task_id}", dependencies=[Depends(verify_csrf)])
def save_task(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task, values)
    try:
        entry = TaskForm.model_validate(values)
    except ValidationError as e:
        return edit_page(request, task, values, form_errors(e), status_code=400)
    update_task(
        task,
        entry.title,
        entry.bucket,
        entry.due_on,
        entry.estimate_minutes,
        entry.ok_to_read_aloud,
    )
    session.commit()
    return back_to_list()


@router.post("/todo/{task_id}/remove", dependencies=[Depends(verify_csrf)])
def remove(request: Request, task_id: int, session: SessionDep):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    remove_task(task)
    session.commit()
    response = back_to_list()
    set_message(response, "task_removed", task.id)
    return response


@router.post("/todo/{task_id}/restore", dependencies=[Depends(verify_csrf)])
def restore(task_id: int, session: SessionDep):
    task = load_task(session, task_id)
    try:
        restore_task(task)
    except TodoStateError:
        return back_to_list()  # already back (Undo twice, or Back): nothing changes
    session.commit()
    return back_to_list()


@router.post("/todo/{task_id}/steps", dependencies=[Depends(verify_csrf)])
def create_step(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task, values)
    try:  # `back` only says where to return; the step form takes just its own fields
        entry = StepForm.model_validate({k: v for k, v in values.items() if k != "back"})
    except ValidationError as e:
        return edit_page(
            request, task, step_values=values, step_errors=form_errors(e), status_code=400
        )
    add_step(session, task, entry.title, entry.minutes)
    session.commit()
    return go_back(values, task, back_to_edit(task))


@router.post("/todo/{task_id}/steps/{step_id}/move", dependencies=[Depends(verify_csrf)])
def reorder_step(
    request: Request, task_id: int, step_id: int, session: SessionDep, values: FormValues
):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    direction = {"up": -1, "down": 1}.get(values.get("direction", ""))
    if direction is None:
        raise HTTPException(status_code=400, detail="Bad request")
    step = load_step(task, step_id)
    if step.removed_at is not None:
        return step_gone(request, task, step)
    move_step(session, task, step, direction)
    session.commit()
    return back_to_edit(task)


@router.post("/todo/{task_id}/steps/{step_id}/done", dependencies=[Depends(verify_csrf)])
def mark_step_done(
    request: Request, task_id: int, step_id: int, session: SessionDep, values: FormValues
):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    step = load_step(task, step_id)
    if step.removed_at is not None:
        return step_gone(request, task, step)
    step.done = values.get("done") == "1"
    session.commit()
    return go_back(values, task, back_to_edit(task))


@router.post("/todo/{task_id}/steps/{step_id}/remove", dependencies=[Depends(verify_csrf)])
def delete_step(request: Request, task_id: int, step_id: int, session: SessionDep):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    step = load_step(task, step_id)
    if step.removed_at is not None:
        return step_gone(request, task, step)
    remove_step(session, task, step)
    session.commit()
    response = back_to_edit(task)
    set_message(response, "step_removed", step.id)
    return response


@router.post("/todo/{task_id}/steps/{step_id}/restore", dependencies=[Depends(verify_csrf)])
def undo_step(request: Request, task_id: int, step_id: int, session: SessionDep):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    try:
        restore_step(session, task, load_step(task, step_id))
    except TodoStateError:
        return back_to_edit(task)  # already back: nothing changes
    session.commit()
    return back_to_edit(task)


@router.post("/todo/{task_id}/read-aloud", dependencies=[Depends(verify_csrf)])
def toggle_read_aloud(request: Request, task_id: int, session: SessionDep, values: FormValues):
    """The card's speaker toggle: "ok to read aloud" on or off (off by default, ADR 0015)."""
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    task.ok_to_read_aloud = values.get("on") == "1"
    session.commit()
    return go_back(values, task, back_to_list())


@router.get("/todo/{task_id}/focus", response_class=HTMLResponse)
def focus(request: Request, task_id: int, session: SessionDep) -> HTMLResponse:
    """One task, its current step and a dot-ring timer: one dot per minute."""
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task)
    minutes = focus_minutes(task)
    return render_form(
        request,
        "todo/focus.html",
        {},
        task=task,
        steps=live_steps(task),
        step=current_step(task),
        minutes=minutes,
        ring=ring(minutes),
    )


def ring(count: int, size: int = 240) -> list[tuple[float, float, float]]:
    """(cx, cy, r) for each minute's dot around a circle, starting at the top. Drawn as SVG
    attributes, so the page needs no inline styles (CSP)."""
    centre, radius = size / 2, size / 2 - 14
    dot = max(2.2, min(7.0, math.pi * radius / count * 0.42))
    points = []
    for i in range(count):
        angle = -math.pi / 2 + 2 * math.pi * i / count
        cx = centre + radius * math.cos(angle)
        cy = centre + radius * math.sin(angle)
        points.append((round(cx, 2), round(cy, 2), round(dot, 2)))
    return points
