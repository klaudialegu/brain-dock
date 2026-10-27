"""Kill switches (ADR 0007, 0008): a file stops agents, checked before every tool call, so it
works mid-run; and if checking fails, agents count as off."""

from pathlib import Path

import pytest
from sqlmodel import Session, select

from brain_dock.core.agents import killswitch
from brain_dock.core.agents.audit import AuditEvent, AuditKey, AuditLog
from brain_dock.core.agents.passes import Dispatcher, PassOffice
from brain_dock.core.db import get_engine, migrate

from .test_capability_pass import INBOX, PREP, QUERY, calls


@pytest.fixture
def setup(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'agents.db'}")
    migrate(engine)
    calls.clear()
    office = PassOffice([INBOX, PREP])
    dispatcher = Dispatcher(
        office, AuditLog(engine, AuditKey(b"k" * 32)), [INBOX, PREP], lambda: tmp_path
    )
    yield tmp_path, office, dispatcher, engine
    engine.dispose()


def reasons(engine):
    with Session(engine) as session:
        return [(r.module, r.reason) for r in session.exec(select(AuditEvent))]


def test_global_switch_stops_every_module(setup):
    folder, office, dispatcher, engine = setup
    (folder / "agents-off").touch()

    inbox = dispatcher.call(office.issue("inbox", "r1"), "list_jobs", QUERY)
    prep = dispatcher.call(office.issue("prep", "r2"), "read_prep_notes", QUERY)

    assert not inbox.ok and not prep.ok and calls == []
    assert reasons(engine) == [("inbox", "kill_switch"), ("prep", "kill_switch")]


def test_module_switch_stops_only_that_module(setup):
    folder, office, dispatcher, engine = setup
    (folder / "agents-off-inbox").touch()

    inbox = dispatcher.call(office.issue("inbox", "r1"), "list_jobs", QUERY)
    prep = dispatcher.call(office.issue("prep", "r2"), "read_prep_notes", QUERY)

    assert not inbox.ok and prep.ok
    assert reasons(engine) == [("inbox", "kill_switch"), ("prep", "ok")]


def test_switch_works_mid_run_and_can_be_turned_back(setup):
    folder, office, dispatcher, engine = setup
    issued = office.issue("inbox", "r1")

    first = dispatcher.call(issued, "list_jobs", QUERY)
    (folder / "agents-off").touch()
    second = dispatcher.call(issued, "list_jobs", QUERY)
    (folder / "agents-off").unlink()
    third = dispatcher.call(issued, "list_jobs", QUERY)

    assert [first.ok, second.ok, third.ok] == [True, False, True]


def test_an_error_while_checking_means_agents_off(setup, monkeypatch):
    folder, office, dispatcher, engine = setup

    def broken(self):
        raise PermissionError("can't look")

    monkeypatch.setattr(Path, "exists", broken)

    assert killswitch.agents_allowed(folder, "inbox") is False
    monkeypatch.undo()  # the dispatcher's audit write needs the file system back
    monkeypatch.setattr(killswitch, "switch_paths", lambda f, m: 1 / 0)

    result = dispatcher.call(office.issue("inbox", "r1"), "list_jobs", QUERY)

    assert not result.ok and calls == []
    assert reasons(engine) == [("inbox", "kill_switch")]
