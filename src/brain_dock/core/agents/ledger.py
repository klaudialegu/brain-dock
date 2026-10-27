"""The token and cost ledger (ADR 0008): one row per model call attempt, written before the
call (outcome "started", fail closed) and completed after it. No prompt or answer text.

Cost is NULL when it's unknown: a row still "started" (the process stopped mid-call) or an
attempt that got no answer (the API may still have billed it). 0 always means free.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Field, Session, SQLModel, func, select

from brain_dock.core.agents.prices import Usage


class LLMCall(SQLModel, table=True):
    __tablename__ = "core_llm_call"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime  # timezone-aware, stored as UTC
    run_id: str = Field(index=True)
    module: str
    route: str  # "cheap" or "escalated" (design section 3)
    model: str
    prompt_version: str
    attempt: int
    # started, ok, timeout, server_error, malformed, refused, failed, budget_stopped
    outcome: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_micro_usd: int | None = None  # NULL: unknown; 0: free
    prices_verified: bool


NO_USAGE = Usage()  # a call that never got an answer


class LedgerWriteError(RuntimeError):
    """A ledger row couldn't be written. The call it describes doesn't go ahead."""


@dataclass
class RunBudget:
    """A run's hard limit and what it has spent, in micro-dollars."""

    limit_micro_usd: int
    spent_micro_usd: int = 0

    def would_exceed(self, worst_case_micro_usd: int) -> bool:
        return self.spent_micro_usd + worst_case_micro_usd > self.limit_micro_usd


class Ledger:
    def __init__(self, engine: Engine):
        self.engine = engine

    def start(self, **fields) -> int:
        """Write the row before the call; returns its id."""
        try:
            with Session(self.engine) as session:
                row = LLMCall(at=datetime.now(UTC), outcome="started", **fields)
                session.add(row)
                session.commit()
                return row.id
        except Exception as e:
            raise LedgerWriteError("couldn't write the ledger") from e

    def finish(
        self, row_id: int, outcome: str, usage: Usage = NO_USAGE, cost: int | None = None
    ) -> None:
        """Complete the row. Leave cost as None when it's unknown (no answer came back)."""
        try:
            with Session(self.engine) as session:
                row = session.get(LLMCall, row_id)
                row.outcome = outcome
                row.input_tokens = usage.input_tokens
                row.output_tokens = usage.output_tokens
                row.cache_read_tokens = usage.cache_read_tokens
                row.cache_write_tokens = usage.cache_write_tokens
                row.cost_micro_usd = cost
                session.commit()
        except Exception as e:
            raise LedgerWriteError("couldn't write the ledger") from e


@dataclass(frozen=True)
class RouteCost:
    known_micro_usd: int  # the sum of every cost that's known
    unknown_attempts: int  # attempts whose cost is unknown (so the real total may be higher)


def cost_by_route(engine: Engine, run_id: str) -> dict[str, RouteCost]:
    """Cost per route for one run (the ledger's 'cost per email per route')."""
    with Session(engine) as session:
        rows = session.exec(
            select(
                LLMCall.route,
                func.sum(LLMCall.cost_micro_usd),
                func.count().filter(LLMCall.cost_micro_usd.is_(None)),
            )
            .where(LLMCall.run_id == run_id)
            .group_by(LLMCall.route)
        )
        return {route: RouteCost(int(known or 0), unknown) for route, known, unknown in rows}
