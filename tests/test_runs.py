"""Durable agent runs (ADR 0008, harness PR 4a): work items with idempotent keys, a declared
workflow, parking instead of dropping, resume after a crash with the spending kept, and the
whole run inside the network guard."""

import dataclasses
import hashlib
import socket
import threading

import pytest
from pydantic import BaseModel
from sqlmodel import Session, select

from brain_dock import registry
from brain_dock.core.agents.audit import AuditEvent, AuditKey, AuditLog
from brain_dock.core.agents.gateway import (
    ModelRequest,
    ModelResponse,
    NeedsReviewError,
    RetryPolicy,
    ScriptedClient,
    redact,
)
from brain_dock.core.agents.passes import Dispatcher, PassOffice
from brain_dock.core.agents.prices import Usage, load_prices
from brain_dock.core.agents.run_tables import AgentRun, RunStep, WorkItem
from brain_dock.core.agents.runs import (
    NEEDS_REVIEW,
    IllegalTransitionError,
    ItemKey,
    Items,
    Runner,
    Steps,
    Workflow,
)
from brain_dock.core.agents.tools import AgentTool, Effect
from brain_dock.core.db import get_engine, migrate

from .conftest import SECRET

KEYS = Items(None, AuditKey(b"k" * 32))  # key_for() needs only the audit key


def key(name: str) -> ItemKey:
    """The key for a natural key (an email's Message-ID): a keyed hash made by the core."""
    return KEYS.key_for("inbox", name)


NAMES = ["ok", "skip", "review", "bug", "wait", "crash", "spend", "dns", "illegal", "worker"]
BY_KEY = {key(n).value: n for n in NAMES}  # stored key -> the test's name for it
calls: list[tuple[str, str]] = []
crash_once = {"armed": False}


class Crash(BaseException):
    """Stands in for the process dying mid-run (not an Exception, so nothing catches it)."""


class NoInput(BaseModel):
    pass


worker_errors: list[BaseException] = []
worker_go = threading.Event()


def start_worker(_data):
    """A tool that leaves a thread running after it returns, which later tries to reach out."""

    def later():
        worker_go.wait(5)
        try:
            socket.getaddrinfo("collector.invalid", 443)
        except BaseException as e:  # noqa: BLE001 (the test inspects what happened)
            worker_errors.append(e)

    thread = threading.Thread(target=later, daemon=True)
    thread.start()
    start_worker.thread = thread
    return {"started": True}


INBOX = dataclasses.replace(
    registry.installed()[0],
    name="inbox",
    agent_tools=(AgentTool("start_worker", "Starts a worker", NoInput, Effect.read, start_worker),),
)

SONNET = load_prices()["claude-sonnet-5-5"]
ANSWER = ModelResponse({"label": "fit"}, Usage(input_tokens=1000, output_tokens=100))
ANSWER_COST = SONNET.cost_micro_usd(ANSWER.usage)


def judge(ctx, item) -> ModelResponse:
    return ctx.gateway.call(
        ModelRequest(
            run_id=ctx.run_id,
            module=ctx.module,
            route="cheap",
            model="claude-sonnet-5-5",
            prompt_version="test-v1",
            system=redact("Judge fit."),
            untrusted=redact("A synthetic job"),
            max_tokens=100,
        )
    )


def on_received(ctx, item):
    name = BY_KEY[item.key]
    calls.append((name, "received"))
    if name == "review":
        raise NeedsReviewError("timeout")
    if name == "bug":
        raise ValueError("a bug in the step")
    if name == "dns":
        socket.getaddrinfo("collector.invalid", 443)  # straight from a step, not a tool
    if name == "illegal":
        return "suggested"  # skipping "judged" isn't allowed
    return "skipped" if name == "skip" else "judged"


def on_judged(ctx, item):
    name = BY_KEY[item.key]
    calls.append((name, "judged"))
    if name == "crash" and crash_once["armed"]:
        crash_once["armed"] = False
        raise Crash()
    if name == "spend":
        judge(ctx, item)
    if name == "worker":
        result = ctx.dispatcher.call(ctx.capability_pass, "start_worker", {})
        assert result.ok  # the tool call itself finished
        worker_go.set()  # the thread it left behind now tries to reach out, mid-run
        start_worker.thread.join(5)
    return "pending_approval" if name == "wait" else "suggested"


WORKFLOW = Workflow(
    module="inbox",
    transitions={
        "received": frozenset({"judged", "skipped"}),
        "judged": frozenset({"suggested", "pending_approval"}),
    },
    final=frozenset({"suggested", "skipped", NEEDS_REVIEW}),
    waiting=frozenset({"pending_approval"}),
    steps={"received": on_received, "judged": on_judged},
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "runs.db"
    engine = get_engine(f"sqlite:///{path}")
    migrate(engine)
    engine.dispose()
    calls.clear()
    worker_errors.clear()
    worker_go.clear()
    crash_once["armed"] = False
    return path


def make_runner(db_path, folder, answers=(ANSWER,) * 5):
    """A runner on its own engine, as after a restart: nothing shared but the file."""
    engine = get_engine(f"sqlite:///{db_path}")
    audit = AuditLog(engine, AuditKey(b"k" * 32))
    office = PassOffice([INBOX])
    dispatcher = Dispatcher(office, audit, [INBOX], lambda: folder)
    runner = Runner(
        engine,
        audit,
        office,
        dispatcher,
        ScriptedClient(list(answers)),
        retry=RetryPolicy(sleep=lambda _: None),
        switch_folder=lambda: folder,
    )
    return runner, engine


def states(engine):
    with Session(engine) as session:
        return {BY_KEY[i.key]: (i.state, i.reason) for i in session.exec(select(WorkItem))}


def run_row(engine, run_id):
    with Session(engine) as session:
        return session.get(AgentRun, run_id)


# --- Work items --------------------------------------------------------------------------


def test_a_duplicate_key_returns_the_same_item(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)

    first, new_first = runner.items.receive("inbox", key("ok"))
    again, new_again = runner.items.receive("inbox", key("ok"))
    runner.run(WORKFLOW, runner.start("inbox", 1_000_000), [key("ok"), key("ok")])

    assert (new_first, new_again) == (True, False) and first.id == again.id
    assert calls == [("ok", "received"), ("ok", "judged")]  # one item, worked on once
    with Session(engine) as session:
        assert len(session.exec(select(WorkItem)).all()) == 1


@pytest.mark.parametrize(
    "bad_key", ["Senior Support Engineer at Acme", f"msg-{SECRET}", "abc", "ABCDEF0123456789"]
)
def test_keys_must_be_hashes_never_content(db_path, tmp_path, bad_key):
    runner, _ = make_runner(db_path, tmp_path)

    # Content, a made-up value, or even a real hex hash: only key_for() makes a key.
    with pytest.raises(TypeError, match="key_for"):
        runner.items.receive("inbox", bad_key)


def test_an_illegal_state_change_is_refused(db_path, tmp_path):
    runner, _ = make_runner(db_path, tmp_path)
    item, _ = runner.items.receive("inbox", key("ok"))

    with pytest.raises(IllegalTransitionError):
        runner.items.advance(WORKFLOW, item.id, "suggested")  # received can't skip judging
    assert runner.items.get(item.id).state == "received"


def test_a_final_item_cannot_move_or_be_parked(db_path, tmp_path):
    runner, _ = make_runner(db_path, tmp_path)
    item, _ = runner.items.receive("inbox", key("skip"))
    runner.items.advance(WORKFLOW, item.id, "skipped")

    with pytest.raises(IllegalTransitionError):
        runner.items.park(WORKFLOW, item.id, "late")


# --- Never dropped ----------------------------------------------------------------------


def test_every_item_ends_final_or_waiting_and_none_is_dropped(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)
    names = ["ok", "skip", "review", "bug", "wait", "illegal"]

    report = runner.run(WORKFLOW, runner.start("inbox", 1_000_000), [key(n) for n in names])

    assert states(engine) == {
        "ok": ("suggested", None),
        "skip": ("skipped", None),
        "review": (NEEDS_REVIEW, "timeout"),  # NeedsReviewError keeps its reason
        "bug": (NEEDS_REVIEW, "step_error"),  # any step error parks, never drops
        "wait": ("pending_approval", None),
        "illegal": (NEEDS_REVIEW, "illegal_transition"),
    }
    assert report.status == "finished" and sum(report.states.values()) == len(names)
    resting = WORKFLOW.final | WORKFLOW.waiting
    assert all(state in resting for state, _ in states(engine).values())
    assert runner.items.unfinished(WORKFLOW) == []  # waiting items aren't "unfinished" work


# --- Restarts ----------------------------------------------------------------------------


def test_a_run_resumes_after_a_crash_without_redoing_steps(db_path, tmp_path):
    crash_once["armed"] = True
    runner, engine = make_runner(db_path, tmp_path)
    run_id = runner.start("inbox", 1_000_000)

    with pytest.raises(Crash):
        runner.run(WORKFLOW, run_id, [key("ok"), key("crash"), key("skip")])
    assert run_row(engine, run_id).status == "running"  # interrupted, resumable
    engine.dispose()

    restarted, engine = make_runner(db_path, tmp_path)  # a fresh process: new engine, objects
    report = restarted.run(WORKFLOW, run_id)

    assert report.status == "finished"
    assert states(engine) == {
        "ok": ("suggested", None),
        "crash": ("suggested", None),
        "skip": ("skipped", None),
    }
    # Before the crash: ok fully, crash received and judged (then died). After: crash's
    # judging again, skip from the start. Nothing that finished ran twice.
    assert calls == [
        ("ok", "received"),
        ("ok", "judged"),
        ("crash", "received"),
        ("crash", "judged"),
        ("crash", "judged"),
        ("skip", "received"),
    ]
    with Session(engine) as session:
        attempts = {BY_KEY[i.key]: i.attempts for i in session.exec(select(WorkItem))}
    assert attempts == {"ok": 2, "crash": 3, "skip": 1}  # every step start is counted


def test_the_spending_survives_a_restart(db_path, tmp_path):
    crash_once["armed"] = True
    limit = 2 * SONNET.worst_case_micro_usd(10_000, 100)
    runner, engine = make_runner(db_path, tmp_path)
    run_id = runner.start("inbox", limit)

    with pytest.raises(Crash):
        runner.run(WORKFLOW, run_id, [key("spend"), key("crash")])
    assert run_row(engine, run_id).spent_micro_usd == ANSWER_COST
    engine.dispose()

    restarted, engine = make_runner(db_path, tmp_path)
    restarted.run(WORKFLOW, run_id)

    assert run_row(engine, run_id).spent_micro_usd == ANSWER_COST  # kept, not reset to 0


def test_a_budget_stop_ends_the_run_and_the_item_waits(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)
    run_id = runner.start("inbox", 10)  # 10 micro-dollars: below any model call's worst case

    report = runner.run(WORKFLOW, run_id, [key("spend"), key("ok")])

    assert report.status == "budget_stopped" and run_row(engine, run_id).status == "budget_stopped"
    assert run_row(engine, run_id).spent_micro_usd == 0  # stopped before sending
    assert states(engine) == {"spend": ("judged", None), "ok": ("received", None)}  # not dropped


def test_a_kill_switch_stops_the_run_and_items_wait(db_path, tmp_path):
    (tmp_path / "agents-off-inbox").touch()
    runner, engine = make_runner(db_path, tmp_path)

    run_id = runner.start("inbox", 1_000_000)
    report = runner.run(WORKFLOW, run_id, [key("ok")])

    assert report.status == "stopped" and calls == []
    assert states(engine) == {"ok": ("received", None)}  # recorded, not dropped
    with Session(engine) as session:  # stopped before the run began: nothing recorded
        assert session.exec(select(RunStep).where(RunStep.run_id == run_id)).all() == []
    (tmp_path / "agents-off-inbox").unlink()
    runner.run(WORKFLOW, runner.start("inbox", 1_000_000))  # a new run picks it up
    assert states(engine) == {"ok": ("suggested", None)}


def test_only_a_running_run_of_the_module_can_run(db_path, tmp_path):
    runner, _ = make_runner(db_path, tmp_path)
    run_id = runner.start("inbox", 1_000_000)
    runner.run(WORKFLOW, run_id, [key("ok")])

    with pytest.raises(ValueError, match="running"):
        runner.run(WORKFLOW, run_id)  # finished runs stay finished
    with pytest.raises(ValueError, match="running"):
        runner.run(WORKFLOW, "no-such-run")


# --- The whole run is guarded ------------------------------------------------------------


def test_the_whole_run_is_guarded_not_just_tool_calls(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)

    runner.run(WORKFLOW, runner.start("inbox", 1_000_000), [key("dns")])

    assert states(engine) == {"dns": (NEEDS_REVIEW, "guard_refused")}
    with Session(engine) as session:
        audited = [(r.tool, r.reason) for r in session.exec(select(AuditEvent))]
    assert ("run", "guard_dns") in audited


def test_a_thread_a_tool_leaves_running_stays_guarded_for_the_run(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)

    runner.run(WORKFLOW, runner.start("inbox", 1_000_000), [key("worker")])

    assert states(engine) == {"worker": ("suggested", None)}
    assert len(worker_errors) == 1 and "refused" in str(worker_errors[0])


# --- The flight recorder -----------------------------------------------------------------


def test_step_details_must_be_redacted(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)
    steps = Steps(engine)

    with pytest.raises(TypeError, match="Redacted"):
        steps.record("run-1", "note", detail="Reply to jane.doe@example.com")
    step = steps.record("run-1", "note", detail=redact("Reply to jane.doe@example.com"))

    assert step.detail == "Reply to [email]"


def test_steps_are_numbered_in_order(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)
    run_id = runner.start("inbox", 1_000_000)

    runner.run(WORKFLOW, run_id, [key("ok"), key("skip")])

    with Session(engine) as session:
        rows = session.exec(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq))
        kinds = [(s.seq, s.kind, s.decision) for s in rows]
    assert kinds == [
        (1, "received", None),
        (2, "received", None),
        (3, "step", "judged"),
        (4, "step", "suggested"),
        (5, "step", "skipped"),
    ]


def test_core_run_tables_hold_no_content(db_path, tmp_path):
    runner, engine = make_runner(db_path, tmp_path)
    secret_key = key(f"<message-id-{SECRET}@mail.example.com>")
    BY_KEY[secret_key.value] = "ok"

    runner.run(WORKFLOW, runner.start("inbox", 1_000_000), [secret_key])

    with engine.connect() as connection:
        dump = "\n".join(connection.connection.iterdump())
    assert "core_work_item" in dump and SECRET not in dump


def test_workflow_definitions_are_checked():
    assert WORKFLOW.problems() == []
    broken = Workflow(
        module="inbox",
        transitions={"received": frozenset({"judged"}), "done": frozenset({"received"})},
        final=frozenset({"done"}),
        steps={"done": on_judged},
    )

    assert broken.problems() == [
        "inbox: needs_review must be a final state",
        "inbox: working state 'judged' has no step",
        "inbox: working state 'received' has no step",
        "inbox: final or waiting state 'done' can't have a step",
        "inbox: final state 'done' can't move on",
        "inbox: 'received' needs a step",
    ]


# --- Added in 4b: kill switches on resume, keyed item keys ------------------------------


def test_a_resumed_run_checks_the_kill_switch_before_anything_runs(db_path, tmp_path):
    crash_once["armed"] = True
    runner, engine = make_runner(db_path, tmp_path)
    run_id = runner.start("inbox", 1_000_000)
    with pytest.raises(Crash):
        runner.run(WORKFLOW, run_id, [key("ok"), key("crash")])
    engine.dispose()
    calls_before = list(calls)
    (tmp_path / "agents-off").touch()  # someone stops agents before the restart

    restarted, engine = make_runner(db_path, tmp_path)
    report = restarted.run(WORKFLOW, run_id)

    assert report.status == "stopped" and calls == calls_before  # no step ran
    assert states(engine)["crash"] == ("judged", None)  # waiting where it stopped
    (tmp_path / "agents-off").unlink()
    restarted.run(WORKFLOW, restarted.start("inbox", 1_000_000))
    assert states(engine)["crash"] == ("suggested", None)


def test_item_keys_are_keyed_hashes_not_plain_hashes():
    natural = "<CAF123@mail.example.com>"
    ours = KEYS.key_for("inbox", natural).value

    assert ours == KEYS.key_for("inbox", natural).value  # the same email, the same key
    assert ours != hashlib.sha256(natural.encode()).hexdigest()  # not guessable by hashing
    assert ours != Items(None, AuditKey(b"j" * 32)).key_for("inbox", natural).value
    assert ours != KEYS.key_for("prep", natural).value  # each module has its own keys
