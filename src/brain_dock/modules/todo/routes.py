"""To-do pages: the card (Today and Can wait) with an add form, and the edit page with steps.

Plain form posts with CSRF (ADR 0005), no scripts. Nothing here logs a title.
Remove keeps the task or step for Undo (ADR 0018). A removed task refuses every change
(say, from a page left open in another tab) with a page that offers Undo, never a bare 404.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
    done_on,
    done_recently,
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
    return back_to_list()


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
    return back_to_list()


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
        return Response("Nothing to undo", status_code=409)  # a live task: nothing changes
    session.commit()
    return back_to_list()


@router.post("/todo/{task_id}/steps", dependencies=[Depends(verify_csrf)])
def create_step(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    if task.removed_at is not None:
        return removed_page(request, task, values)
    try:
        entry = StepForm.model_validate(values)
    except ValidationError as e:
        return edit_page(
            request, task, step_values=values, step_errors=form_errors(e), status_code=400
        )
    add_step(session, task, entry.title, entry.minutes)
    session.commit()
    return back_to_edit(task)


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
    return back_to_edit(task)


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
        return Response("Nothing to undo", status_code=409)  # a live step: nothing changes
    session.commit()
    return back_to_edit(task)
