"""The To do card on Home and Focus mode (ADR 0016)."""

import re
from datetime import date

from sqlmodel import select

from brain_dock.modules.todo.models import (
    TodoTask,
    add_step,
    add_task,
    dot_count,
    focus_minutes,
)

from .conftest import BASE_URL


def token(client, path="/"):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text).group(1)


def post(client, path, data, page="/"):
    return client.post(
        path,
        data={**data, "csrf_token": token(client, page)},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )


def fresh(session, task_id):
    session.expire_all()
    return session.get(TodoTask, task_id)


def test_dot_meter_is_one_dot_per_15_minutes_max_4(client, session):
    cases = {None: 0, 1: 1, 15: 1, 16: 2, 45: 3, 60: 4, 61: 4, 600: 4}
    for minutes, dots in cases.items():
        assert dot_count(TodoTask(title="t", estimate_minutes=minutes)) == dots, minutes
    by_steps = add_task(session, "Steps only")
    session.flush()
    add_step(session, by_steps, "a", 20)
    add_step(session, by_steps, "b", 20)
    session.commit()
    assert dot_count(by_steps) == 3  # no estimate: the steps' 40 minutes
    html = client.get("/").text
    meter = re.search(r'<span class="dot-meter"[^>]*>(.*?)</span></span>', html, re.S)
    assert meter.group(1).count('class="on"') == 3 and meter.group(1).count('class="off"') == 1


def test_speaker_toggle_sets_read_aloud_and_defaults_off(client, session):
    task = add_task(session, "Water the plants")
    session.commit()
    html = client.get("/").text
    assert 'aria-pressed="false" aria-label="Ok to read aloud: Water the plants"' in html

    on = post(client, f"/todo/{task.id}/read-aloud", {"on": "1", "back": "home"})
    assert on.status_code == 303 and on.headers["location"] == "/"
    assert fresh(session, task.id).ok_to_read_aloud is True
    assert (
        'aria-pressed="true" aria-label="Ok to read aloud: Water the plants"'
        in client.get("/").text
    )
    post(client, f"/todo/{task.id}/read-aloud", {"on": "0", "back": "home"})
    assert fresh(session, task.id).ok_to_read_aloud is False
    post(client, f"/todo/{task.id}/read-aloud", {"on": "yes please", "back": "home"})
    assert fresh(session, task.id).ok_to_read_aloud is False  # only "1" turns it on


def test_focus_timer_length_uses_step_then_estimate_then_25(client, session):
    plain = add_task(session, "No estimate")
    estimated = add_task(session, "Estimated", estimate_minutes=40)
    stepped = add_task(session, "With steps", estimate_minutes=40)
    huge = add_task(session, "Huge", estimate_minutes=600)
    session.flush()
    first = add_step(session, stepped, "First", 10)
    add_step(session, stepped, "Second", None)
    session.commit()

    assert focus_minutes(plain) == 25
    assert focus_minutes(estimated) == 40
    assert focus_minutes(stepped) == 10  # the current step's minutes
    first.done = True
    session.commit()
    assert focus_minutes(stepped) == 40  # the next step has none: the task's estimate
    assert focus_minutes(huge) == 120  # capped: one dot per minute stays readable
    html = client.get(f"/todo/{estimated.id}/focus").text
    assert html.count("data-minute=") == 40 and 'data-minutes="40"' in html  # a dot per minute


def test_done_next_step_marks_the_step(client, session):
    task = add_task(session, "Write it")
    session.flush()
    one = add_step(session, task, "Outline", 10)
    two = add_step(session, task, "Draft", 15)
    session.commit()
    page = client.get(f"/todo/{task.id}/focus").text
    assert "Step 1 of 2: <strong>Outline</strong>" in page
    assert f'action="/todo/{task.id}/steps/{one.id}/done"' in page

    done = post(
        client,
        f"/todo/{task.id}/steps/{one.id}/done",
        {"done": "1", "back": "focus"},
        page=f"/todo/{task.id}/focus",
    )
    assert done.headers["location"] == f"/todo/{task.id}/focus"  # stays in Focus
    session.expire_all()
    assert (one.done, two.done) == (True, False)
    assert "Step 2 of 2: <strong>Draft</strong>" in client.get(f"/todo/{task.id}/focus").text
    post(
        client,
        f"/todo/{task.id}/steps/{two.id}/done",
        {"done": "1", "back": "focus"},
        page=f"/todo/{task.id}/focus",
    )
    last = client.get(f"/todo/{task.id}/focus").text
    assert "Every step is done." in last and f'action="/todo/{task.id}/done"' in last


def test_park_a_thought_posts_to_the_capture_path(client, session):
    task = add_task(session, "Focus here")
    session.commit()
    page = client.get(f"/todo/{task.id}/focus").text
    assert '<form class="park" method="post" action="/scratchpad/capture" data-park>' in page
    parked = client.post(
        "/scratchpad/capture",
        data={"text": "a parked thought", "csrf_token": token(client, f"/todo/{task.id}/focus")},
        headers={"Origin": BASE_URL, "x-scratchpad-capture": "1"},
    )
    assert parked.status_code == 204  # the script stays on the Focus page
    assert "a parked thought" in client.get("/scratchpad").text


def test_no_park_bar_when_no_module_captures(client, session):
    task = add_task(session, "Focus here")
    session.commit()
    client.post(
        "/settings/cards/scratchpad/shown",
        data={"shown": "0", "csrf_token": token(client, "/settings")},
        headers={"Origin": BASE_URL},
    )
    page = client.get(f"/todo/{task.id}/focus").text
    assert 'class="park"' not in page and "Park a thought" not in page
    assert "data-minute=" in page  # the rest of Focus still works


def test_card_forms_come_back_home_and_never_follow_an_address(client, session):
    task = add_task(session, "Parked task", bucket="can_wait")
    session.commit()
    html = client.get("/").text
    assert 'name="back" value="home"' in html  # the card's ↑ Today form
    assert 'name="next"' not in html

    for back in ["home", "https://example.com/", "//example.com", "/elsewhere"]:
        moved = post(client, f"/todo/{task.id}/bucket", {"bucket": "today", "back": back})
        expected = "/" if back == "home" else "/todo"  # anything else: the To do page
        assert moved.headers["location"] == expected, back
    stepped = post(
        client, f"/todo/{task.id}/steps", {"title": "From the card", "minutes": "", "back": "home"}
    )
    assert stepped.headers["location"] == "/"
    assert [t.title for t in session.exec(select(TodoTask)).all()] == ["Parked task"]
    assert date.today()  # the card used the real today


def test_break_into_steps_is_quiet_only_for_tasks_without_steps(client, session):
    plain = add_task(session, "No steps yet")
    stepped = add_task(session, "Has steps")
    session.flush()
    add_step(session, stepped, "One", 5)
    session.commit()
    html = client.get("/").text

    def details_for(title):
        start = html.index(f'<span class="tcard-title">{title}</span>')
        return re.search(r'<details class="([^"]+)">', html[start:]).group(1)

    assert details_for("No steps yet") == "tcard-steps no-steps"  # shows on hover or focus
    assert details_for("Has steps") == "tcard-steps"  # "1 step" always shown
    assert plain.id and "1 step<span" in html
