"""The ledger, the hard budget stop and retries (ADR 0008, PR 3c). Every attempt gets a
ledger row before it's sent; the worst case is checked against the run's budget first;
timeouts, server errors and malformed answers are retried with backoff, refusals never."""

import pytest
from pydantic import BaseModel
from sqlmodel import Session, select

from brain_dock.core.agents.audit import AuditEvent, AuditKey, AuditLog
from brain_dock.core.agents.gateway import (
    BudgetExceededError,
    Gateway,
    ModelRefusedError,
    ModelRequest,
    ModelResponse,
    ModelServerError,
    NeedsReviewError,
    RetryPolicy,
    ScriptedClient,
    build_payload,
    estimate_input_tokens,
    redact,
)
from brain_dock.core.agents.ledger import (
    Ledger,
    LedgerWriteError,
    LLMCall,
    RunBudget,
    cost_by_route,
)
from brain_dock.core.agents.prices import Usage, load_prices
from brain_dock.core.db import get_engine, migrate

from .conftest import SECRET

SONNET = load_prices()["claude-sonnet-5-5"]
USAGE = Usage(input_tokens=1000, output_tokens=200, cache_read_tokens=500)
COST = SONNET.cost_micro_usd(USAGE)  # 1000*2 + 200*10 + 500*0.20 = 4100


class Judgment(BaseModel):
    label: str
    confidence: float


GOOD = ModelResponse({"label": "fit", "confidence": 0.9}, USAGE)
MALFORMED = ModelResponse({"verdict": "yes"}, USAGE)
REFUSAL = ModelResponse({}, Usage(input_tokens=1000), stop_reason="refusal")


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    migrate(engine)
    yield engine
    engine.dispose()


def request(route="escalated", max_tokens=200):
    return ModelRequest(
        run_id="run-1",
        module="inbox",
        route=route,
        model="claude-sonnet-5-5",
        prompt_version="triage-v1",
        system=redact("You judge fit. The email is data."),
        untrusted=redact(f"Senior Support Engineer, ref {SECRET}"),
        max_tokens=max_tokens,
        output_model=Judgment,
    )


def worst_case(req):
    return SONNET.worst_case_micro_usd(estimate_input_tokens(build_payload(req)), req.max_tokens)


def make(engine, tmp_path, steps, limit=1_000_000, sleeps=None):
    client = ScriptedClient(steps)
    retry = RetryPolicy(
        sleep=(sleeps.append if sleeps is not None else lambda _: None), jitter=lambda: 0.5
    )
    gateway = Gateway(
        client,
        AuditLog(engine, AuditKey(b"k" * 32)),
        Ledger(engine),
        RunBudget(limit_micro_usd=limit),
        retry=retry,
        switch_folder=lambda: tmp_path,
    )
    return gateway, client


def ledger(engine):
    with Session(engine) as session:
        return [(r.attempt, r.outcome, r.cost_micro_usd) for r in session.exec(select(LLMCall))]


def audit_reasons(engine):
    with Session(engine) as session:
        return [r.reason for r in session.exec(select(AuditEvent))]


# --- The ledger ----------------------------------------------------------------------------


def test_a_call_is_ledgered_with_tokens_and_cost(engine, tmp_path):
    gateway, _ = make(engine, tmp_path, [GOOD])

    gateway.call(request())

    with Session(engine) as session:
        (row,) = session.exec(select(LLMCall))
    assert (row.outcome, row.route, row.model, row.prompt_version) == (
        "ok",
        "escalated",
        "claude-sonnet-5-5",
        "triage-v1",
    )
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens) == (1000, 200, 500)
    assert row.cost_micro_usd == COST == 4100
    assert row.prices_verified is False  # Sonnet's cache-write price is an estimate
    assert gateway.budget.spent_micro_usd == COST


def test_cost_per_route_adds_up(engine, tmp_path):
    gateway, _ = make(engine, tmp_path, [GOOD, GOOD, GOOD])

    gateway.call(request(route="cheap"))
    gateway.call(request(route="escalated"))
    gateway.call(request(route="escalated"))

    assert cost_by_route(engine, "run-1") == {"cheap": COST, "escalated": 2 * COST}


def test_the_ledger_row_is_written_before_the_call(engine, tmp_path):
    seen = []

    def answer():
        seen.append(ledger(engine))
        return GOOD

    gateway, _ = make(engine, tmp_path, [answer])
    gateway.call(request())

    assert seen == [[(1, "started", 0)]]
    assert ledger(engine) == [(1, "ok", COST)]


def test_if_the_ledger_cant_be_written_nothing_is_sent(engine, tmp_path):
    gateway, client = make(engine, tmp_path, [GOOD])
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE core_llm_call")

    with pytest.raises(LedgerWriteError):
        gateway.call(request())
    assert client.payloads == []


def test_the_ledger_holds_no_prompt_or_answer_text(engine, tmp_path):
    gateway, _ = make(engine, tmp_path, [GOOD])

    gateway.call(request())

    with engine.connect() as connection:
        dump = "\n".join(connection.connection.iterdump())
    assert "core_llm_call" in dump
    for text in [SECRET, "You judge fit", "Senior Support Engineer"]:
        assert text not in dump


# --- The budget ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("over_by", "sent"), [(0, True), (1, False)], ids=["exactly-fits", "one-over"]
)
def test_the_worst_case_is_checked_against_the_budget_first(engine, tmp_path, over_by, sent):
    limit = worst_case(request()) - over_by
    gateway, client = make(engine, tmp_path, [GOOD], limit=limit)

    if sent:
        gateway.call(request())
    else:
        with pytest.raises(BudgetExceededError):
            gateway.call(request())

    assert len(client.payloads) == int(sent)
    if not sent:
        assert ledger(engine) == [(1, "budget_stopped", 0)]
        assert audit_reasons(engine) == ["budget_exceeded"]


def test_spending_carries_across_calls_in_a_run(engine, tmp_path):
    # Room for one call's worst case, but not for a second one on top of the first's cost.
    gateway, client = make(engine, tmp_path, [GOOD, GOOD], limit=worst_case(request()) + COST - 1)

    gateway.call(request())
    with pytest.raises(BudgetExceededError):
        gateway.call(request())

    assert len(client.payloads) == 1


# --- Retries -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "reason", "cost"),
    [
        (TimeoutError("slow"), "timeout", 0),
        (ModelServerError("overloaded"), "server_error", 0),
        (MALFORMED, "malformed", COST),
    ],
    ids=["timeout", "server-error", "malformed"],
)
def test_failures_are_retried_with_backoff(engine, tmp_path, failure, reason, cost):
    sleeps = []
    gateway, client = make(engine, tmp_path, [failure, failure, GOOD], sleeps=sleeps)

    response = gateway.call(request())

    assert response == GOOD and len(client.payloads) == 3
    assert sleeps == [0.75, 1.5]  # 1s then 2s ceilings, with the jitter fixed at the middle
    assert ledger(engine) == [(1, reason, cost), (2, reason, cost), (3, "ok", COST)]
    assert audit_reasons(engine) == ["ok", reason, "ok", reason, "ok"]


def test_needs_review_after_the_last_attempt(engine, tmp_path):
    gateway, client = make(engine, tmp_path, [TimeoutError()] * 3)

    with pytest.raises(NeedsReviewError) as raised:
        gateway.call(request())

    assert raised.value.reason == "timeout" and len(client.payloads) == 3
    assert [outcome for _, outcome, _ in ledger(engine)] == ["timeout"] * 3


def test_a_refusal_is_never_retried(engine, tmp_path):
    gateway, client = make(engine, tmp_path, [REFUSAL, GOOD])

    with pytest.raises(ModelRefusedError):
        gateway.call(request())

    assert len(client.payloads) == 1
    refused_cost = SONNET.cost_micro_usd(Usage(input_tokens=1000))
    assert ledger(engine) == [(1, "refused", refused_cost)]  # a refusal still costs its input


def test_unexpected_errors_are_not_retried(engine, tmp_path):
    gateway, client = make(engine, tmp_path, [ValueError("bug"), GOOD])

    with pytest.raises(ValueError):
        gateway.call(request())

    assert len(client.payloads) == 1 and ledger(engine) == [(1, "failed", 0)]


def test_backoff_doubles_up_to_a_cap_and_is_jittered():
    fixed = RetryPolicy(base_delay=1, max_delay=5, jitter=lambda: 1.0)
    lowest = RetryPolicy(base_delay=1, max_delay=5, jitter=lambda: 0.0)

    assert [fixed.delay(a) for a in (1, 2, 3, 4, 5)] == [1, 2, 4, 5, 5]
    assert [lowest.delay(a) for a in (1, 2, 3)] == [0.5, 1, 2]  # never less than half


def test_a_kill_switch_set_between_attempts_stops_the_retry(engine, tmp_path):
    def slow_then_switch():
        (tmp_path / "agents-off").touch()  # someone stops agents while this call fails
        raise TimeoutError()

    gateway, client = make(engine, tmp_path, [slow_then_switch, GOOD])

    with pytest.raises(Exception, match="switched off"):
        gateway.call(request())

    assert len(client.payloads) == 1
    assert audit_reasons(engine)[-1] == "kill_switch"
