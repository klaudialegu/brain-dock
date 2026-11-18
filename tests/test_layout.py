"""Home's layout and the shell's settings, saved in the database (ADR 0016)."""

import pytest

from brain_dock import registry
from brain_dock.core import layout
from brain_dock.core.brief import lines_by_module
from brain_dock.core.layout import LayoutError
from brain_dock.core.shell import CORE_CARDS

from .test_home import form_post

MODULES = registry.installed()


def order(session):
    return [(p.card.id, p.shown, p.size) for p in layout.layout(session, MODULES, CORE_CARDS)]


def test_defaults_come_from_the_manifests(session):
    assert order(session) == [
        ("todo", True, "W"),
        ("brief", True, "M"),
        ("job_search", True, "L"),
        ("inbox", True, "S"),
    ]
    assert layout.highlighter(session) == "lavender"
    assert session.exec(layout.select(layout.CoreLayout)).all() == []  # nothing saved yet


def test_order_on_off_and_size_are_saved(client, session):
    for path, data in [
        ("/settings/cards/inbox/move", {"direction": "up"}),
        ("/settings/cards/brief/shown", {"shown": "0"}),
        ("/settings/cards/job_search/size", {"size": "M"}),
    ]:
        assert form_post(client, path, data).status_code == 303

    session.expire_all()
    assert order(session) == [
        ("todo", True, "W"),
        ("brief", False, "M"),
        ("inbox", True, "S"),
        ("job_search", True, "M"),
    ]
    assert (
        form_post(client, "/settings/cards/inbox/move", {"direction": "sideways"}).status_code
        == 400
    )
    assert form_post(client, "/settings/cards/nope/shown", {"shown": "1"}).status_code == 400


def test_a_size_the_card_doesnt_support_is_refused(client, session):
    with pytest.raises(LayoutError):
        layout.set_size(session, MODULES, "inbox", "W", CORE_CARDS)  # inbox: S or M only
    assert form_post(client, "/settings/cards/inbox/size", {"size": "W"}).status_code == 400
    assert form_post(client, "/settings/cards/inbox/size", {"size": "XL"}).status_code == 400
    session.expire_all()
    assert ("inbox", True, "S") in order(session)


def test_hidden_module_keeps_its_page_and_data(client, session):
    from brain_dock.modules.todo.models import add_task

    add_task(session, "Still here")
    session.commit()
    form_post(client, "/settings/cards/todo/shown", {"shown": "0"})

    home = client.get("/").text
    assert 'aria-labelledby="card-todo"' not in home  # off Home
    assert 'aria-label="To do"' not in home  # and out of the rail
    page = client.get("/todo")
    assert page.status_code == 200 and "Still here" in page.text  # its page and data stay


def test_hidden_module_leaves_the_brief(client, session):
    from brain_dock.modules.todo.models import add_task

    add_task(session, "Counted")
    session.commit()
    today = __import__("datetime").date.today()
    assert "todo" in lines_by_module(session, today, MODULES)

    form_post(client, "/settings/cards/todo/shown", {"shown": "0"})
    session.expire_all()

    assert "todo" not in lines_by_module(session, today, MODULES)  # so it's never spoken
    assert "On today's list" not in client.get("/brief").text


def test_highlighter_of_the_day_is_saved_and_must_be_a_palette_color(client, session):
    assert form_post(client, "/settings/highlighter", {"highlighter": "sage"}).status_code == 303
    session.expire_all()
    assert layout.highlighter(session) == "sage"
    assert 'class=" hl-sage"' in client.get("/").text or "hl-sage" in client.get("/").text
    assert form_post(client, "/settings/highlighter", {"highlighter": "red"}).status_code == 400
    session.expire_all()
    assert layout.highlighter(session) == "sage"
