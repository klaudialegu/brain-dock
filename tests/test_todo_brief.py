"""To-dos in the brief and the morning brief (ADR 0015): a count, and titles only for tasks
marked "ok to read aloud"."""

import hashlib
from datetime import date, timedelta

from sqlmodel import select

from brain_dock.core import db
from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.todo import demo
from brain_dock.modules.todo.brief import brief_lines, spoken_title
from brain_dock.modules.todo.models import TodoTask, add_task, set_done
from brain_dock.morning_brief import SIGN_OFF, Sources, build_script

TODAY = date(2026, 11, 18)


def test_brief_counts_todays_open_tasks(session):
    assert brief_lines(session, TODAY) == []  # nothing for today: no to-do line at all

    add_task(session, "In today")
    add_task(session, "Parked, due today", bucket="can_wait", due_on=TODAY)
    add_task(session, "Parked, overdue", bucket="can_wait", due_on=TODAY - timedelta(days=3))
    add_task(session, "Parked for later", bucket="can_wait", due_on=TODAY + timedelta(days=1))
    set_done(add_task(session, "Already done"), True)
    session.commit()

    assert brief_lines(session, TODAY) == ["On today's list: 3 things."]
    for task in session.exec(select(TodoTask).where(TodoTask.title != "In today")).all():
        task.done = True
    session.commit()
    assert brief_lines(session, TODAY) == ["On today's list: 1 thing."]


def test_only_tasks_marked_read_aloud_are_named(session):
    add_task(session, "Private dentist appointment")
    add_task(session, "Water the plants", ok_to_read_aloud=True)
    add_task(session, "Parked and marked", bucket="can_wait", ok_to_read_aloud=True)
    set_done(add_task(session, "Done and marked", ok_to_read_aloud=True), True)
    session.commit()

    lines = brief_lines(session, TODAY)

    assert lines == ["On today's list: 2 things.", "First up: Water the plants."]
    text = " ".join(lines)
    for unmarked_or_not_today in ["dentist", "Parked and marked", "Done and marked"]:
        assert unmarked_or_not_today not in text


def test_spoken_titles_are_cleaned_trimmed_and_at_most_two(session):
    assert spoken_title("Zadzwoń do mamy 📞 <b>now</b>!") == "Zadzwoń do mamy b now /b"
    assert spoken_title("snake_case_title") == "snake case title"
    long = "Finish the quarterly planning document and send it to the whole group"
    assert spoken_title(long) == "Finish the quarterly planning document"
    assert len(spoken_title(long)) <= 40
    word = "'".join(["abcdefghij"] * 6)  # one 65-character word, not key-shaped
    assert spoken_title(word) == word[:40]  # cut at 40, not 41
    for title in ["First marked", "Second marked", "Third marked"]:
        add_task(session, title, ok_to_read_aloud=True)
    session.commit()

    lines = brief_lines(session, TODAY)

    assert lines[1] == "First up: First marked, and Second marked."  # at most 2, in order
    assert "Third" not in " ".join(lines)


def test_morning_brief_reads_todos_before_job_counts_and_drops_titles_first():
    sources = Sources(
        greeting_name="Avery",
        todo_lines=["On today's list: 3 things.", "First up: Water the plants."],
        job_lines=["2 follow-ups are overdue.", "1 offer is open."],
    )

    script = build_script(TODAY, sources)
    assert script == (
        "Good morning, Avery, it's Wednesday, November 18th. On today's list: 3 things. "
        "First up: Water the plants. On the job front... 2 follow-ups are overdue. "
        f"1 offer is open. {SIGN_OFF}"
    )
    shorter = build_script(TODAY, sources, limit=len(script) - 1)
    assert "Water the plants" not in shorter  # the titles go first
    assert "On today's list: 3 things." in shorter and "1 offer is open." in shorter


def test_todo_demo_writes_only_the_demo_database(tmp_path, monkeypatch):
    real = db.DB_PATH  # the test's stand-in for data/brain_dock.db (conftest)
    engine = get_engine()
    migrate(engine)
    engine.dispose()
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    demo_db = tmp_path / "demo" / "demo.db"

    assert "isn't ready" in demo.load_demo(demo_db)  # no file: nothing created
    assert not demo_db.exists()
    demo_db.parent.mkdir()
    engine = get_engine(f"sqlite:///{demo_db}")
    migrate(engine)
    engine.dispose()

    monkeypatch.setenv("BRAIN_DOCK_DB", str(real))  # pointing at "the real one" changes nothing
    monkeypatch.setattr(db, "DEMO_DB_PATH", demo_db)
    assert demo.main() == 0
    assert "already has tasks" in demo.load_demo(demo_db)  # a second run adds nothing

    assert hashlib.sha256(real.read_bytes()).hexdigest() == before
    engine = get_engine(f"sqlite:///{demo_db}")
    with engine.connect() as connection:
        count = connection.exec_driver_sql("SELECT count(*) FROM todo_task").scalar()
        read_aloud = connection.exec_driver_sql(
            "SELECT count(*) FROM todo_task WHERE ok_to_read_aloud"
        ).scalar()
    engine.dispose()
    assert (count, read_aloud) == (5, 1)
