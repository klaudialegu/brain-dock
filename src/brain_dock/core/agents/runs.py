"""Durable agent runs (ADR 0008, design section 4; harness PR 4a).

A module declares a Workflow: the states its work items move through, which state changes
are allowed, which states are final or waiting (for me), and a step function per working
state. The Runner drives every unfinished item to a final or waiting state, inside the
network guard for the whole run. Nothing is dropped silently: a step that fails parks its
item as needs_review with a reason. Runs, items and steps live in the database, so a run
interrupted by a crash or restart resumes where it stopped, with its spending.

The core holds no content: item keys are hex digests (the module hashes its natural key),
and the flight recorder's step detail must be Redacted text.
"""

import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from brain_dock.core.agents.audit import AuditLog
from brain_dock.core.agents.gateway import (
    DEFAULT_RETRY,
    AgentsOffError,
    BudgetExceededError,
    Gateway,
    ModelClient,
    NeedsReviewError,
    Redacted,
    RetryPolicy,
)
from brain_dock.core.agents.guard import NetworkGuardError, guarded_run
from brain_dock.core.agents.killswitch import agents_allowed
from brain_dock.core.agents.ledger import Ledger, RunBudget
from brain_dock.core.agents.passes import (
    CapabilityPass,
    Dispatcher,
    PassOffice,
    default_switch_folder,
)
from brain_dock.core.agents.prices import ModelPrices
from brain_dock.core.agents.run_tables import AgentRun, RunStep, WorkItem

RECEIVED = "received"  # every item starts here
NEEDS_REVIEW = "needs_review"  # every workflow can park an item here; always final
HEX_KEY = re.compile(r"[0-9a-f]{16,128}")


def _now() -> datetime:
    return datetime.now(UTC)


# --- Workflows ---------------------------------------------------------------------------


class IllegalTransitionError(ValueError):
    """The workflow doesn't allow this state change. Nothing changed."""


@dataclass(frozen=True)
class Workflow:
    module: str
    transitions: Mapping[str, frozenset[str]]  # state -> the states it may move to
    final: frozenset[str]  # where items end (needs_review is always one)
    steps: Mapping[str, Callable[["StepContext", WorkItem], str]]  # working state -> step
    waiting: frozenset[str] = frozenset()  # items rest here until I act (e.g. approvals)

    def allows(self, from_state: str, to_state: str) -> bool:
        if from_state in self.final:
            return False
        return to_state == NEEDS_REVIEW or to_state in self.transitions.get(from_state, ())

    def problems(self) -> list[str]:
        """Everything wrong with the definition; empty means it's sound."""
        problems = []
        resting = self.final | self.waiting
        known = (
            set(self.transitions) | resting | {t for ts in self.transitions.values() for t in ts}
        )
        if NEEDS_REVIEW not in self.final:
            problems.append(f"{self.module}: {NEEDS_REVIEW} must be a final state")
        for state in sorted(known - resting):
            if state not in self.steps:
                problems.append(f"{self.module}: working state {state!r} has no step")
        for state in sorted(set(self.steps) & resting):
            problems.append(f"{self.module}: final or waiting state {state!r} can't have a step")
        for state in sorted(set(self.transitions) & self.final):
            if self.transitions[state]:
                problems.append(f"{self.module}: final state {state!r} can't move on")
        if RECEIVED not in self.steps:
            problems.append(f"{self.module}: {RECEIVED!r} needs a step")
        return problems


# --- Items and steps ---------------------------------------------------------------------


class Items:
    def __init__(self, engine: Engine):
        self.engine = engine

    def receive(self, module: str, key: str) -> tuple[WorkItem, bool]:
        """The item for this key: (existing, False) for a duplicate, (new, True) otherwise."""
        if not HEX_KEY.fullmatch(key):
            raise ValueError("work item keys must be hex digests of the natural key, never content")
        with Session(self.engine) as session:
            query = select(WorkItem).where(WorkItem.module == module, WorkItem.key == key)
            existing = session.exec(query).first()
            if existing is not None:
                return existing, False
            now = _now()
            item = WorkItem(module=module, key=key, state=RECEIVED, created_at=now, updated_at=now)
            session.add(item)
            try:
                session.commit()
            except IntegrityError:  # received at the same moment elsewhere: same item
                session.rollback()
                return session.exec(query).one(), False
            session.refresh(item)
            return item, True

    def get(self, item_id: int) -> WorkItem:
        with Session(self.engine) as session:
            return session.get(WorkItem, item_id)

    def _update(self, item_id: int, **changes) -> WorkItem:
        with Session(self.engine) as session:
            item = session.get(WorkItem, item_id)
            for name, value in changes.items():
                setattr(item, name, value)
            item.updated_at = _now()
            session.commit()
            session.refresh(item)
            return item

    def advance(
        self, workflow: Workflow, item_id: int, to_state: str, reason: str | None = None
    ) -> WorkItem:
        item = self.get(item_id)
        if not workflow.allows(item.state, to_state):
            raise IllegalTransitionError(f"{item.state} -> {to_state} isn't allowed")
        return self._update(item_id, state=to_state, reason=reason)

    def park(self, workflow: Workflow, item_id: int, reason: str) -> WorkItem:
        """Set aside for a person to look at, with the reason. Never a silent drop."""
        return self.advance(workflow, item_id, NEEDS_REVIEW, reason)

    def started(self, item_id: int, run_id: str) -> WorkItem:
        item = self.get(item_id)
        return self._update(item_id, attempts=item.attempts + 1, run_id=run_id)

    def unfinished(self, workflow: Workflow) -> list[WorkItem]:
        resting = workflow.final | workflow.waiting
        with Session(self.engine) as session:
            items = session.exec(
                select(WorkItem).where(WorkItem.module == workflow.module).order_by(WorkItem.id)
            ).all()
            return [i for i in items if i.state not in resting]


class Steps:
    def __init__(self, engine: Engine):
        self.engine = engine

    def record(
        self, run_id: str, kind: str, *, detail: Redacted | None = None, **fields
    ) -> RunStep:
        if detail is not None and not isinstance(detail, Redacted):
            raise TypeError("the flight recorder only stores Redacted text; use redact()")
        with Session(self.engine) as session:
            last = session.exec(select(func.max(RunStep.seq)).where(RunStep.run_id == run_id)).one()
            step = RunStep(
                run_id=run_id,
                seq=(last or 0) + 1,
                kind=kind,
                detail=detail.text if detail is not None else None,
                at=_now(),
                **fields,
            )
            session.add(step)
            session.commit()
            session.refresh(step)
            return step


# --- The runner --------------------------------------------------------------------------


@dataclass
class StepContext:
    """What a step can use: its pass (through the dispatcher), the gateway, the recorder."""

    run_id: str
    module: str
    capability_pass: CapabilityPass
    dispatcher: Dispatcher
    gateway: Gateway
    steps: Steps

    def record(self, kind: str, **fields) -> RunStep:
        return self.steps.record(self.run_id, kind, **fields)


@dataclass(frozen=True)
class RunReport:
    run_id: str
    status: str
    states: dict[str, int] = field(default_factory=dict)  # item counts by state


class Runner:
    def __init__(
        self,
        engine: Engine,
        audit: AuditLog,
        office: PassOffice,
        dispatcher: Dispatcher,
        client: ModelClient,
        *,
        allow: Iterable[tuple[str, int]] = (),  # the model API's host:port (PR 9)
        prices: dict[str, ModelPrices] | None = None,
        retry: RetryPolicy = DEFAULT_RETRY,
        switch_folder: Callable = default_switch_folder,
    ):
        self.engine = engine
        self.audit = audit
        self.office = office
        self.dispatcher = dispatcher
        self.client = client
        self.allow = tuple(allow)
        self.prices = prices
        self.retry = retry
        self._switch_folder = switch_folder
        self.items = Items(engine)
        self.steps = Steps(engine)

    def start(self, module: str, budget_limit_micro_usd: int) -> str:
        run_id = uuid.uuid4().hex
        with Session(self.engine) as session:
            session.add(
                AgentRun(
                    id=run_id,
                    module=module,
                    status="running",
                    started_at=_now(),
                    budget_limit_micro_usd=budget_limit_micro_usd,
                )
            )
            session.commit()
        return run_id

    def _save(self, run_id: str, spent: int, status: str | None = None) -> None:
        with Session(self.engine) as session:
            run = session.get(AgentRun, run_id)
            run.spent_micro_usd = spent
            if status is not None:
                run.status = status
                run.finished_at = _now()
            session.commit()

    def run(self, workflow: Workflow, run_id: str, new_keys: Iterable[str] = ()) -> RunReport:
        """Receive new keys, then drive every unfinished item of the module. Also resumes an
        interrupted run: its status is still "running" and its spending is kept."""
        with Session(self.engine) as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.status != "running" or run.module != workflow.module:
                raise ValueError("only a running (or interrupted) run of this module can run")
            budget = RunBudget(run.budget_limit_micro_usd, run.spent_micro_usd)
        gateway = Gateway(
            self.client,
            self.audit,
            Ledger(self.engine),
            budget,
            prices=self.prices,
            retry=self.retry,
            allow=self.allow,
            switch_folder=self._switch_folder,
        )
        context = StepContext(
            run_id,
            workflow.module,
            self.office.issue(workflow.module, run_id),
            self.dispatcher,
            gateway,
            self.steps,
        )

        def refused(reason: str) -> None:
            self.audit.record(
                run_id=run_id,
                module=workflow.module,
                tool="run",
                outcome="blocked",
                reason=reason,
                input_mac=self.audit.input_mac(None),
            )

        status = "finished"
        try:
            # The whole run is guarded, so a thread a tool leaves behind stays guarded too.
            with guarded_run(self.allow, on_refusal=refused):
                for key in new_keys:
                    item, new = self.items.receive(workflow.module, key)
                    if new:
                        context.record("received", item_id=item.id)
                for item in self.items.unfinished(workflow):
                    if not agents_allowed(self._switch_folder(), workflow.module):
                        status = "stopped"
                        break
                    try:
                        self._drive(workflow, context, item)
                    except BudgetExceededError:
                        status = "budget_stopped"
                        break
                    except AgentsOffError:
                        status = "stopped"
                        break
        except BaseException:
            # A crash: keep the spending, leave the run "running" so it can be resumed.
            self._save(run_id, budget.spent_micro_usd)
            raise
        self._save(run_id, budget.spent_micro_usd, status)
        return RunReport(run_id, status, self._counts(workflow))

    def _drive(self, workflow: Workflow, context: StepContext, item: WorkItem) -> None:
        resting = workflow.final | workflow.waiting
        while item.state not in resting:
            item = self.items.started(item.id, context.run_id)
            try:
                next_state = workflow.steps[item.state](context, item)
            except (BudgetExceededError, AgentsOffError):
                raise  # the run stops; the item waits where it is for the next run
            except NeedsReviewError as e:
                self._park(workflow, context, item, e.reason)
                return
            except NetworkGuardError:
                self._park(workflow, context, item, "guard_refused")
                return
            except Exception:
                self._park(workflow, context, item, "step_error")
                return
            try:
                item = self.items.advance(workflow, item.id, next_state)
            except IllegalTransitionError:
                self._park(workflow, context, item, "illegal_transition")
                return
            context.record("step", item_id=item.id, decision=item.state)

    def _park(self, workflow: Workflow, context: StepContext, item: WorkItem, reason: str) -> None:
        self.items.park(workflow, item.id, reason)
        context.record("parked", item_id=item.id, reason=reason)

    def _counts(self, workflow: Workflow) -> dict[str, int]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(WorkItem.state, func.count())
                .where(WorkItem.module == workflow.module)
                .group_by(WorkItem.state)
            )
            return dict(rows.all())
