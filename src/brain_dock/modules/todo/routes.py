"""To-do pages: the card (Today and Can wait) with an add form, and the edit page with steps.

Plain form posts with CSRF (ADR 0005), no scripts. Nothing here logs a title.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session

from brain_dock.core.security import verify_csrf
from brain_dock.core.web import FormValues, SessionDep, render_form
from brain_dock.modules.todo.models import (
    TodoFieldError,
    TodoStep,
    TodoTask,
    add_step,
    add_task,
    card,
    meta,
    move_step,
    move_to,
    remove_step,
    set_done,
    total_minutes,
    update_task,
    when_label,
)
from brain_dock.modules.todo.schemas import StepForm, TaskForm, form_errors

router = APIRouter()
BUCKET_OPTIONS = [("today", "Today"), ("can_wait", "Can wait")]


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
        bucket_options=BUCKET_OPTIONS,
    )


def load_task(session: Session, task_id: int) -> TodoTask:
    task = session.get(TodoTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    return task


def load_step(task: TodoTask, step_id: int) -> TodoStep:
    step = next((s for s in task.steps if s.id == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail="Not found")
    return step


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
) -> HTMLResponse:
    return render_form(
        request,
        "todo/edit.html",
        values if values is not None else task_values(task),
        errors,
        status_code,
        task=task,
        steps=sorted(task.steps, key=lambda s: s.position),
        total=total_minutes(task),
        step_values=step_values or {},
        step_errors=step_errors or {},
        bucket_options=BUCKET_OPTIONS,
    )


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
def mark_done(task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    set_done(task, values.get("done") == "1")
    session.commit()
    return back_to_list()


@router.post("/todo/{task_id}/bucket", dependencies=[Depends(verify_csrf)])
def change_bucket(task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    try:
        move_to(task, values.get("bucket", ""))
    except TodoFieldError:
        raise HTTPException(status_code=400, detail="Bad request") from None
    session.commit()
    return back_to_list()


@router.get("/todo/{task_id}/edit", response_class=HTMLResponse)
def edit_task(request: Request, task_id: int, session: SessionDep) -> HTMLResponse:
    return edit_page(request, load_task(session, task_id))


@router.post("/todo/{task_id}", dependencies=[Depends(verify_csrf)])
def save_task(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
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


@router.post("/todo/{task_id}/steps", dependencies=[Depends(verify_csrf)])
def create_step(request: Request, task_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
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
def reorder_step(task_id: int, step_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    direction = {"up": -1, "down": 1}.get(values.get("direction", ""))
    if direction is None:
        raise HTTPException(status_code=400, detail="Bad request")
    move_step(session, task, load_step(task, step_id), direction)
    session.commit()
    return back_to_edit(task)


@router.post("/todo/{task_id}/steps/{step_id}/done", dependencies=[Depends(verify_csrf)])
def mark_step_done(task_id: int, step_id: int, session: SessionDep, values: FormValues):
    task = load_task(session, task_id)
    load_step(task, step_id).done = values.get("done") == "1"
    session.commit()
    return back_to_edit(task)


@router.post("/todo/{task_id}/steps/{step_id}/remove", dependencies=[Depends(verify_csrf)])
def delete_step(task_id: int, step_id: int, session: SessionDep):
    task = load_task(session, task_id)
    remove_step(session, task, load_step(task, step_id))
    session.commit()
    return back_to_edit(task)
