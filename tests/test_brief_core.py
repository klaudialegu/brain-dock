"""The Brief card and page live in the core (ADR 0016)."""

from datetime import date

from brain_dock import registry
from brain_dock.core import brief as core_brief
from brain_dock.core.modules import CardContext
from brain_dock.core.shell import brief_card


def test_brief_card_uses_the_apps_modules_not_the_registry(session, monkeypatch):
    from brain_dock.modules.todo.models import add_task

    add_task(session, "One thing")
    session.commit()
    todo = registry.INSTALLED["todo"]

    with_todo = brief_card(CardContext(session, date.today(), (todo,)))
    without = brief_card(CardContext(session, date.today(), ()))

    assert with_todo.context["lines"] == ["On today's list: 1 thing."]
    assert without.empty and without.empty_line == core_brief.NOTHING
    # That the core never imports the registry is test_core_boundaries.py's job.
