"""The to-do module (ADR 0015): tasks, steps, the card, and the forms."""

import logging
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from brain_dock.modules.todo import models
from brain_dock.modules.todo.models import (
    TodoFieldError,
    TodoStep,
    TodoTask,
    add_step,
    add_task,
    card,
    live_steps,
    meta,
    move_step,
    remove_step,
    set_done,
    when_label,
)

from .conftest import BASE_URL, SECRET

TODAY = date(2026, 11, 18)  # a Wednesday
PACIFIC = ZoneInfo("America/Los_Angeles")


def form_token(client):
    response = client.get("/todo")
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def post(client, path, data=None):
    return client.post(
        path,
        data={**(data or {}), "csrf_token": form_token(client)},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )


def tasks(session):
    session.expire_all()
    return session.exec(select(TodoTask).order_by(TodoTask.id)).all()


# --- Tasks and steps -------------------------------------------------------------------


def test_task_defaults_are_today_not_done_and_not_read_aloud(session):
    task = add_task(session, "  Water the plants  ")
    session.commit()

    assert (task.title, task.bucket, task.done, task.done_at) == (
        "Water the plants",
        "today",
        False,
        None,
    )
    assert task.ok_to_read_aloud is False
    assert (task.due_on, task.estimate_minutes, task.steps) == (None, None, [])
    assert TodoTask.model_fields["ok_to_read_aloud"].default is False


def test_task_and_step_fields_are_checked(session):
    for kwargs, named in [
        ({"title": "   "}, "Title"),
        ({"title": "x" * 201}, "Title"),
        ({"title": "ok", "estimate_minutes": 0}, "Estimate"),
        ({"title": "ok", "estimate_minutes": 1441}, "Estimate"),
        ({"title": "ok", "bucket": "tomorrow"}, "Bucket"),
    ]:
        title = kwargs.pop("title")
        with pytest.raises(TodoFieldError, match=named):
            add_task(session, title, **kwargs)
    task = add_task(session, "ok", estimate_minutes=1440, bucket="can_wait")
    for title, minutes, named in [
        ("", 5, "Title"),
        ("step", 0, "Minutes"),
        ("step", 2000, "Minutes"),
    ]:
        with pytest.raises(TodoFieldError, match=named):
            add_step(session, task, title, minutes)
    session.commit()
    assert len(tasks(session)) == 1


def test_steps_keep_their_order_when_added_moved_and_removed(session):
    task = add_task(session, "Write-up")
    a, b, c = (add_step(session, task, name, n) for name, n in [("A", 10), ("B", None), ("C", 5)])
    session.commit()

    def order():
        session.refresh(task)
        return [(s.position, s.title) for s in live_steps(task)]

    assert order() == [(1, "A"), (2, "B"), (3, "C")]
    move_step(session, task, c, -1)
    assert order() == [(1, "A"), (2, "C"), (3, "B")]
    move_step(session, task, a, -1)  # already first: nothing moves
    move_step(session, task, b, +1)  # already last
    assert order() == [(1, "A"), (2, "C"), (3, "B")]
    remove_step(session, task, a)
    session.commit()
    assert order() == [(1, "C"), (2, "B")]
    assert b.minutes is None and c.minutes == 5
    session.add(TodoStep(task_id=task.id, position=1, title="clash"))
    with pytest.raises(IntegrityError):  # positions are unique within a task
        session.commit()


def test_marking_done_records_when_and_undoing_clears_it(session):
    task = add_task(session, "Order groceries")
    evening = datetime(2026, 11, 18, 21, 0, tzinfo=PACIFIC)  # 05:00 UTC the next day

    set_done(task, True, evening)
    session.commit()
    assert task.done and task.done_at is not None
    assert models.done_on(task, PACIFIC) == TODAY  # local day, not the UTC one
    assert models.done_on(task, ZoneInfo("UTC")) == TODAY + timedelta(days=1)

    set_done(task, False)
    assert (task.done, task.done_at) == (False, None)


def test_deleting_a_task_deletes_its_steps(session):
    task = add_task(session, "Write-up")
    add_step(session, task, "One", None)
    add_step(session, task, "Two", None)
    other = add_task(session, "Other")
    add_step(session, other, "Keep me", None)
    session.commit()

    session.delete(task)
    session.commit()

    assert [s.title for s in session.exec(select(TodoStep)).all()] == ["Keep me"]


# --- The page ---------------------------------------------------------------------------


def test_todo_page_shows_today_and_can_wait(client, session, monkeypatch):
    open_task = add_task(session, "Open today", estimate_minutes=45, due_on=TODAY + timedelta(2))
    done_tonight = add_task(session, "Done tonight")
    done_yesterday = add_task(session, "Done yesterday")
    overdue_parked = add_task(
        session, "Parked but overdue", bucket="can_wait", due_on=TODAY - timedelta(days=1)
    )
    add_task(session, "Someday thing", bucket="can_wait")
    add_task(session, "This week thing", bucket="can_wait", due_on=TODAY + timedelta(days=4))
    add_task(session, "Later thing", bucket="can_wait", due_on=date(2026, 11, 30))
    steps_only = add_task(session, "Steps only")
    add_step(session, steps_only, "First", 10)
    add_step(session, steps_only, "Second", 15)
    set_done(done_tonight, True, datetime(2026, 11, 18, 21, 30, tzinfo=PACIFIC))
    set_done(done_yesterday, True, datetime(2026, 11, 17, 9, 0, tzinfo=PACIFIC))
    session.commit()

    today_list, can_wait = card(session, TODAY, PACIFIC)
    assert [t.title for t in today_list] == [
        "Parked but overdue",
        "Open today",
        "Done tonight",
        "Steps only",
    ]
    assert [t.title for t in can_wait] == ["This week thing", "Later thing", "Someday thing"]
    assert [when_label(t.due_on, TODAY) for t in can_wait] == ["this week", "by Nov 30", "someday"]
    assert meta(open_task, TODAY) == "~45 min · due Fri"
    assert meta(overdue_parked, TODAY) == "overdue"
    assert meta(steps_only, TODAY) == "~25 min"  # the steps added up

    class Today(date):
        @classmethod
        def today(cls):
            return TODAY

    monkeypatch.setattr("brain_dock.modules.todo.routes.date", Today)
    monkeypatch.setattr(models, "local_zone", lambda: PACIFIC)
    html = client.get("/todo").text
    lists = html[: html.index('<details class="todo-done">')]  # Today and Can wait
    assert "Done tonight" in lists and "Done yesterday" not in lists  # older done tasks move…
    assert "Done yesterday" in html[html.index('<details class="todo-done">') :]  # …to here
    assert html.index("Today</h2>") < html.index("Open today") < html.index("Can wait</h2>")
    assert html.index("Can wait</h2>") < html.index("Someday thing")
    assert re.search(r'class="todo-item is-done">.*?Done tonight', html, re.S)
    assert "3 open" in html  # done tonight isn't open
    assert "<li>First <span" in html  # steps shown in order on the card


def test_add_task_from_the_form(client, session):
    response = post(
        client,
        "/todo",
        {
            "title": "Book a dentist visit",
            "bucket": "can_wait",
            "due_on": "2026-12-01",
            "estimate_minutes": "15",
            "ok_to_read_aloud": "on",
        },
    )

    assert response.status_code == 303 and response.headers["location"] == "/todo"
    [task] = tasks(session)
    assert (task.title, task.bucket, task.due_on, task.estimate_minutes) == (
        "Book a dentist visit",
        "can_wait",
        date(2026, 12, 1),
        15,
    )
    assert task.ok_to_read_aloud is True
    post(client, "/todo", {"title": "Minimal", "due_on": "", "estimate_minutes": ""})
    minimal = tasks(session)[-1]
    assert (minimal.bucket, minimal.due_on, minimal.estimate_minutes) == ("today", None, None)


def test_add_form_never_pre_checks_read_aloud(client, session):
    for html in [client.get("/todo").text, post(client, "/todo", {"title": ""}).text]:
        box = re.search(r'<input type="checkbox" name="ok_to_read_aloud"[^>]*>', html).group(0)
        assert "checked" not in box  # a fresh form, and one sent back with an error

    post(client, "/todo", {"title": "No box sent"})
    assert tasks(session)[-1].ok_to_read_aloud is False


def test_form_errors_show_next_to_fields_and_save_nothing(client, session):
    for data, field in [
        ({"title": "  "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"title": "ok", "estimate_minutes": "0"}, "estimate_minutes"),
        ({"title": "ok", "estimate_minutes": "lots"}, "estimate_minutes"),
        ({"title": "ok", "due_on": "someday"}, "due_on"),
        ({"title": "ok", "bucket": "tomorrow"}, "bucket"),
    ]:
        response = post(client, "/todo", data)
        assert response.status_code == 400, data
        assert f'id="{field}-error"' in response.text
        assert re.search(rf'name="{field}"[^>]*aria-invalid="true"', response.text)
    extra = post(client, "/todo", {"title": "ok", "is_admin": "1"})
    assert "something unexpected" in extra.text and "is_admin" not in extra.text
    assert tasks(session) == []


def test_done_and_bucket_buttons_change_only_that_task(client, session):
    a, b = add_task(session, "A"), add_task(session, "B")
    session.commit()

    assert post(client, f"/todo/{a.id}/done", {"done": "1"}).status_code == 303
    assert post(client, f"/todo/{b.id}/bucket", {"bucket": "can_wait"}).status_code == 303
    a, b = tasks(session)
    assert (a.done, b.done) == (True, False) and a.done_at is not None
    assert (a.bucket, b.bucket) == ("today", "can_wait")

    post(client, f"/todo/{a.id}/done", {"done": "0"})
    assert tasks(session)[0].done is False
    assert post(client, f"/todo/{b.id}/bucket", {"bucket": "tomorrow"}).status_code == 400
    assert post(client, "/todo/999/done", {"done": "1"}).status_code == 404


def test_edit_task_and_its_steps(client, session):
    task = add_task(session, "Write-up")
    session.commit()
    tid = task.id

    page = client.get(f"/todo/{tid}/edit").text
    assert 'value="Write-up"' in page and "No steps yet" in page
    for title, minutes in [("Outline", "10"), ("Draft", ""), ("Read it out loud", "5")]:
        assert (
            post(client, f"/todo/{tid}/steps", {"title": title, "minutes": minutes}).headers[
                "location"
            ]
            == f"/todo/{tid}/edit"
        )
    assert post(client, f"/todo/{tid}/steps", {"title": ""}).status_code == 400

    steps = {s.title: s.id for s in tasks(session)[0].steps}
    post(client, f"/todo/{tid}/steps/{steps['Read it out loud']}/move", {"direction": "up"})
    post(client, f"/todo/{tid}/steps/{steps['Outline']}/done", {"done": "1"})
    post(client, f"/todo/{tid}/steps/{steps['Draft']}/remove")
    assert (
        post(
            client, f"/todo/{tid}/steps/{steps['Outline']}/move", {"direction": "sideways"}
        ).status_code
        == 400
    )

    task = tasks(session)[0]
    assert [(s.position, s.title, s.minutes, s.done) for s in live_steps(task)] == [
        (1, "Outline", 10, True),
        (2, "Read it out loud", 5, False),
    ]
    saved = post(
        client,
        f"/todo/{tid}",
        {"title": "Final write-up", "bucket": "can_wait", "estimate_minutes": "50"},
    )
    assert saved.status_code == 303
    task = tasks(session)[0]
    assert (task.title, task.bucket, task.estimate_minutes) == ("Final write-up", "can_wait", 50)
    assert task.ok_to_read_aloud is False  # unticked box: off
    assert "~50 min" in client.get(f"/todo/{tid}/edit").text
    assert client.get("/todo/999/edit").status_code == 404


def test_typed_titles_never_appear_in_logs(client, session, caplog):
    caplog.set_level(logging.DEBUG)

    post(client, "/todo", {"title": f"{SECRET} task", "ok_to_read_aloud": "on"})
    post(client, "/todo", {"title": SECRET * 20})  # too long: an error page
    tid = tasks(session)[0].id
    post(client, f"/todo/{tid}/steps", {"title": f"{SECRET} step", "minutes": "5"})
    post(client, f"/todo/{tid}/steps", {"title": f"{SECRET}", "minutes": "nope"})

    assert caplog.records  # the capture works: something was logged
    assert SECRET not in caplog.text
    errors = re.findall(
        r'class="field-error"[^>]*>([^<]*)<', post(client, "/todo", {"title": SECRET * 20}).text
    )
    assert errors and all(SECRET not in e for e in errors)


# --- Remove with Undo (ADR 0018) ---------------------------------------------------------


def edit_token(client, task_id):
    html = client.get(f"/todo/{task_id}/edit").text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_remove_task_hides_it_everywhere(client, session):
    from brain_dock.modules.todo.brief import brief_lines
    from brain_dock.modules.todo.models import done_recently

    today = date.today()
    secret = add_task(session, f"{SECRET} marked", ok_to_read_aloud=True)
    keep = add_task(session, "Water the plants", ok_to_read_aloud=True)
    done_one = add_task(session, "Done and then removed")
    set_done(done_one, True, datetime.now(UTC) - timedelta(days=1))
    session.commit()
    assert brief_lines(session, today)[0] == "On today's list: 2 things."

    post(client, f"/todo/{done_one.id}/remove")
    removed = post(client, f"/todo/{secret.id}/remove")  # the newest message wins
    assert removed.status_code == 303 and removed.headers["location"] == "/todo"
    assert removed.cookies.get("bd_message") == f"task_removed:{secret.id}"

    session.expire_all()
    assert secret.removed_at is not None  # kept, not deleted
    first = client.get("/todo").text
    assert f"Removed: {SECRET} marked" in first  # the bar names it, once, with Undo
    assert SECRET not in client.get("/todo").text  # after that: nowhere on the page
    today_list, can_wait = card(session, today)
    assert secret not in today_list + can_wait and keep in today_list
    assert done_recently(session, today) == []  # a removed done task doesn't come back here
    lines = brief_lines(session, today)
    assert lines[0] == "On today's list: 1 thing." and all(SECRET not in ln for ln in lines)
    assert "Water the plants" in " ".join(lines)  # the live marked task is still named
    assert SECRET not in client.get("/").text and SECRET not in client.get("/brief").text


def test_undo_brings_a_task_back_as_it_was(client, session):
    task = add_task(session, "Call the library", bucket="can_wait", estimate_minutes=10)
    session.flush()
    add_step(session, task, "Find the number", 2)
    session.commit()
    before = (task.title, task.bucket, task.estimate_minutes, task.done)

    post(client, f"/todo/{task.id}/remove")
    page = client.get("/todo").text
    assert "Removed: Call the library" in page and f'action="/todo/{task.id}/restore"' in page
    assert "Removed: Call the library" not in client.get("/todo").text  # shown once only
    undone = post(client, f"/todo/{task.id}/restore")
    assert undone.status_code == 303

    task = tasks(session)[0]
    assert task.removed_at is None
    assert (task.title, task.bucket, task.estimate_minutes, task.done) == before
    assert [s.title for s in live_steps(task)] == ["Find the number"]
    assert "Call the library" in client.get("/todo").text


def test_remove_step_renumbers_and_undo_restores_its_place(client, session):
    task = add_task(session, "Write-up")
    session.flush()
    a, b, c, d = (
        add_step(session, task, t, m) for t, m in [("A", 5), ("B", 10), ("C", 20), ("D", 1)]
    )
    session.commit()

    def order():
        session.expire_all()
        return [(s.position, s.title) for s in live_steps(task)]

    post(client, f"/todo/{task.id}/steps/{b.id}/remove")
    assert order() == [(1, "A"), (2, "C"), (3, "D")]
    page = client.get(f"/todo/{task.id}/edit").text
    assert "Removed step: B" in page and "~26 min" in page  # minutes skip removed steps
    post(client, f"/todo/{task.id}/steps/{c.id}/remove")  # held place 2 too: no clash
    assert order() == [(1, "A"), (2, "D")]
    post(client, f"/todo/{task.id}/steps/{d.id}/move", {"direction": "up"})  # reorder after
    assert order() == [(1, "D"), (2, "A")]
    post(client, f"/todo/{task.id}/steps", {"title": "E", "minutes": ""})  # add after
    assert order() == [(1, "D"), (2, "A"), (3, "E")]

    post(client, f"/todo/{task.id}/steps/{c.id}/restore")
    assert order() == [(1, "D"), (2, "C"), (3, "A"), (4, "E")]  # back at place 2
    post(client, f"/todo/{task.id}/steps/{b.id}/restore")
    assert order() == [(1, "D"), (2, "B"), (3, "C"), (4, "A"), (5, "E")]
    session.expire_all()
    assert all(s.removed_at is None and s.removed_position is None for s in task.steps)


def test_done_recently_lists_last_week_and_not_done_reopens(client, session):
    from brain_dock.modules.todo.models import done_recently

    today = date.today()
    now = datetime.now(UTC)
    week_ago = add_task(session, "Done six days ago")
    set_done(week_ago, True, now - timedelta(days=6))
    too_old = add_task(session, "Done long ago")
    set_done(too_old, True, now - timedelta(days=20))
    tonight = add_task(session, "Done just now")
    set_done(tonight, True, now)
    session.commit()

    assert done_recently(session, today) == [week_ago]  # today's stays in Today, ticked
    page = client.get("/todo").text
    recent = page[page.index('<details class="todo-done">') :]
    assert "<summary>Done recently" in recent and "Done six days ago" in recent
    assert "Done long ago" not in page and "Done just now" not in recent

    assert post(client, f"/todo/{week_ago.id}/done", {"done": "0"}).status_code == 303
    session.expire_all()
    assert week_ago.done is False and week_ago in card(session, today)[0]


def test_removed_task_refuses_edits_keeps_typed_values_and_offers_undo(client, session):
    task = add_task(session, "Plan the week")
    session.commit()
    token = edit_token(client, task.id)  # an edit page left open in another tab…
    post(client, f"/todo/{task.id}/remove")  # …while the task is removed

    refused = client.post(
        f"/todo/{task.id}",
        data={"title": "Plan the whole month", "bucket": "today", "csrf_token": token},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )
    assert refused.status_code == 410
    assert "This task was removed" in refused.text
    assert "Plan the whole month" in refused.text  # what was typed is on screen
    assert f'action="/todo/{task.id}/restore"' in refused.text
    opened = client.get(f"/todo/{task.id}/edit")
    assert opened.status_code == 410 and "This task was removed" in opened.text
    assert 'action="/todo/' + str(task.id) + '"' not in opened.text  # no editor
    assert tasks(session)[0].title == "Plan the week"  # nothing changed
    assert client.get("/todo/999/edit").status_code == 404  # never existed: still a 404


def test_undo_and_changes_refuse_items_in_the_wrong_state(client, session):
    from brain_dock.modules.scratchpad.models import new_page

    task = add_task(session, "Live task")
    session.flush()
    step = add_step(session, task, "Live step", None)
    page = new_page(session, date.today())
    session.commit()

    # Undo on something already back (pressed twice, or after Back): goes where Undo goes
    assert post(client, f"/todo/{task.id}/restore").headers["location"] == "/todo"
    edit = post(client, f"/todo/{task.id}/steps/{step.id}/restore").headers["location"]
    assert edit == f"/todo/{task.id}/edit"
    assert post(client, f"/scratchpad/{page.id}/restore").headers["location"] == (
        f"/scratchpad/{page.id}"
    )
    session.expire_all()
    assert (step.position, step.removed_position) == (1, None)  # nothing shifted

    post(client, f"/todo/{task.id}/remove")
    done = post(client, f"/todo/{task.id}/done", {"done": "1"})
    moved = post(client, f"/todo/{task.id}/bucket", {"bucket": "can_wait"})
    stepped = post(client, f"/todo/{task.id}/steps", {"title": "More"})
    assert done.status_code == moved.status_code == stepped.status_code == 410
    session.expire_all()
    assert (task.done, task.bucket, len(task.steps)) == (False, "today", 1)


def test_every_task_row_has_remove_with_undo(client, session):
    today_task = add_task(session, "Row in Today")
    parked = add_task(session, "Row in Can wait", bucket="can_wait")
    finished = add_task(session, "Row done earlier")
    set_done(finished, True, datetime.now(UTC) - timedelta(days=2))
    session.commit()

    page = client.get("/todo").text
    for task in [today_task, parked, finished]:
        assert f'action="/todo/{task.id}/remove"' in page  # in each list, next to Edit
    row = page[page.index("Row in Today") : page.index("</li>", page.index("Row in Today"))]
    assert row.index("Edit") < row.index("Remove")
    assert 'Remove<span class="visually-hidden">: Row in Today</span>' in row  # named
    assert '<button class="link-button" type="submit">Remove' in row  # a dotted link, not a pill
    removed = post(client, f"/todo/{parked.id}/remove")
    assert removed.headers["location"] == "/todo"
    assert "Removed: Row in Can wait" in client.get("/todo").text  # the same Undo bar


def test_message_close_works_without_scripts_on_pages_drawn_for_a_post(client, session):
    task = add_task(session, "Steps here")
    session.flush()
    step = add_step(session, task, "Gone step", None)
    session.commit()
    token = edit_token(client, task.id)  # an old tab…
    post(client, f"/todo/{task.id}/steps/{step.id}/remove")  # …the step removed elsewhere

    gone = client.post(
        f"/todo/{task.id}/steps/{step.id}/done",
        data={"done": "1", "csrf_token": token},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )
    assert gone.status_code == 410 and "This step was removed" in gone.text
    close = re.search(r'class="message-close" href="([^"]+)"', gone.text).group(1)
    assert close == f"/todo/{task.id}/edit"  # not the POST-only address
    assert client.get(close).status_code == 200
    post(client, f"/todo/{task.id}/remove")
    listed = client.get("/todo").text  # a normal page: × reloads that same page
    assert re.search(r'class="message-close" href="([^"]+)"', listed).group(1) == "/todo"
