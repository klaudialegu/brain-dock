"""The tables behind durable runs (harness PR 4a). Kept apart from runs.py so the core's
database code can register them without importing the gateway."""

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class AgentRun(SQLModel, table=True):
    __tablename__ = "core_agent_run"

    id: str = Field(primary_key=True)
    module: str = Field(index=True)
    status: str  # running (also: interrupted, until resumed), finished, stopped, budget_stopped
    started_at: datetime
    finished_at: datetime | None = None
    budget_limit_micro_usd: int
    spent_micro_usd: int = 0  # persisted, worst-case charges included


class WorkItem(SQLModel, table=True):
    __tablename__ = "core_work_item"
    __table_args__ = (Index("ix_core_work_item_module_key", "module", "key", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    module: str
    key: str  # a hex digest of the module's natural key, never content
    state: str
    reason: str | None = None  # a short code, e.g. why it was parked
    attempts: int = 0  # how many times a step started on it
    run_id: str | None = None  # the run that last worked on it
    created_at: datetime
    updated_at: datetime


class RunStep(SQLModel, table=True):
    """The flight recorder's storage: what each run did, in order."""

    __tablename__ = "core_run_step"
    __table_args__ = (Index("ix_core_run_step_run_seq", "run_id", "seq", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str
    seq: int  # 1, 2, 3... per run
    item_id: int | None = None
    kind: str  # e.g. received, step, parked, model_call, decision
    decision: str | None = None
    reason: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    cost_micro_usd: int | None = None
    detail: str | None = None  # Redacted text only
    at: datetime


class Approval(SQLModel, table=True):
    """A write an agent asked for, waiting for my decision (harness PR 4b)."""

    __tablename__ = "core_approval"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    module: str
    item_id: int | None = None
    tool: str
    input_json: str  # the exact input that will run; ids only, by the write-tool policy
    input_mac: str  # HMAC of that input when the approval was created; checked before running
    # pending -> executing -> executed | failed; or rejected; or needs_review (with a reason)
    status: str
    reason: str | None = None  # a short code, never free text
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None  # "human"
