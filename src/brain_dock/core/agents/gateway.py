"""The LLM gateway (ADR 0008, design section 1): the only code that talks to a model.

Every call: text must be Redacted (plain strings are refused), the kill switches are
checked, the run's budget is checked against the worst case, an audit row and a ledger
row are written before anything is sent (fail closed), and the client runs inside the
network guard with only the model API allowed. Timeouts, server errors and malformed
output are retried with backoff; a refusal never is. The live client comes in PR 9.
"""

import json
import math
import random
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from brain_dock.core.agents.audit import AuditLog
from brain_dock.core.agents.guard import NetworkGuardError, guarded_run
from brain_dock.core.agents.killswitch import agents_allowed
from brain_dock.core.agents.ledger import Ledger, RunBudget
from brain_dock.core.agents.passes import default_switch_folder
from brain_dock.core.agents.prices import ModelPrices, PriceError, Usage, load_prices
from brain_dock.core.agents.tools import AgentTool

# --- Redaction ---------------------------------------------------------------------------

_TOKEN = object()  # only redact() has it, so only redact() makes Redacted text

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_QUERY = re.compile(r"(https?://[^\s?#]+)\?[^\s#]*")
PHONE_CANDIDATE = re.compile(r"(?<![\w+(])\+?\(?\d[\d ().-]{6,}\d(?!\w)")
SIGNATURE = re.compile(r"^-- ?$.*", re.MULTILINE | re.DOTALL)  # the "-- " line and after
PHONE_MIN_DIGITS = 9  # dates (8 digits) and salaries stay; phone numbers go
# Local numbers like 555-1234 have only 7 digits, so they get their own pattern. It also
# catches ranges like "100-1000": over-redaction, the safe direction.
LOCAL_PHONE = re.compile(r"(?<![\w.,-])\d{3}[-. ]\d{4}(?![\w.,-])")


class Redacted:
    """Text that went through redact(). The gateway sends nothing else."""

    __slots__ = ("text",)

    def __init__(self, text: str, token: object = None):
        if token is not _TOKEN:
            raise TypeError("only redact() makes Redacted text")
        self.text = text

    def __repr__(self) -> str:
        return f"Redacted({len(self.text)} characters)"


def _phone(match: re.Match) -> str:
    digits = sum(c.isdigit() for c in match.group(0))
    return "[phone]" if digits >= PHONE_MIN_DIGITS else match.group(0)


def redact(text: str, extra_terms: Iterable[str] = ()) -> Redacted:
    """Strip what a model doesn't need: signatures, email addresses, URL query strings
    (tracking and login tokens), phone numbers, and any extra terms (names, places)."""
    text = SIGNATURE.sub("[signature removed]", text)
    text = EMAIL.sub("[email]", text)
    text = URL_QUERY.sub(r"\1?[query removed]", text)
    text = PHONE_CANDIDATE.sub(_phone, text)
    text = LOCAL_PHONE.sub("[phone]", text)
    for term in sorted({t.strip() for t in extra_terms if t.strip()}, key=len, reverse=True):
        text = re.sub(re.escape(term), "[redacted]", text, flags=re.IGNORECASE)
    return Redacted(text, _TOKEN)


# --- Requests and clients ----------------------------------------------------------------

UNTRUSTED_OPEN = "<untrusted_email>"
UNTRUSTED_CLOSE = "</untrusted_email>"


@dataclass(frozen=True)
class ModelRequest:
    run_id: str
    module: str
    route: str  # "cheap" or "escalated" (design section 3)
    model: str
    prompt_version: str
    system: Redacted  # the frozen system prompt
    untrusted: Redacted  # the email: data, never instructions
    tools: Sequence[AgentTool] = ()
    max_tokens: int = 1024
    output_model: type[BaseModel] | None = None  # the answer must match it, or it's malformed


@dataclass(frozen=True)
class ModelResponse:
    content: dict
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "end_turn"


class ModelClient(Protocol):
    def complete(self, payload: dict) -> ModelResponse: ...


class ScriptedClient:
    """Replays scripted steps in order: a ModelResponse is returned, an exception raised.
    For tests and rogue-agent scripts; keeps every payload it was sent."""

    def __init__(self, steps: Iterable[ModelResponse | Exception | Callable[[], ModelResponse]]):
        self.steps = list(steps)
        self.payloads: list[dict] = []

    def complete(self, payload: dict) -> ModelResponse:
        self.payloads.append(payload)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step() if callable(step) else step


def build_payload(request: ModelRequest) -> dict:
    """The request in Messages API shape. The cached prefix renders tools, then system;
    the breakpoint sits at the end of the system prompt, and the email comes after it."""
    tools = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_model.model_json_schema(),
        }
        for t in sorted(request.tools, key=lambda t: t.name)  # fixed order, or no cache hits
    ]
    # The email can't close its own block and pose as instructions after it.
    body = request.untrusted.text.replace(UNTRUSTED_CLOSE, "[/untrusted_email]")
    payload = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "system": [
            {"type": "text", "text": request.system.text, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{UNTRUSTED_OPEN}\n{body}\n{UNTRUSTED_CLOSE}"}
                ],
            }
        ],
    }
    if tools:
        payload["tools"] = tools
    return payload


def estimate_input_tokens(payload: dict) -> int:
    """A deliberate over-estimate for the budget check: one token per 3 bytes (real text
    averages closer to 4), so the worst case is never too low. Needs no network."""
    return math.ceil(len(payload_text(payload).encode()) / 3)


# --- The gateway -------------------------------------------------------------------------


class AgentsOffError(RuntimeError):
    """A kill switch is set (or couldn't be checked). Nothing was sent."""


class BudgetExceededError(RuntimeError):
    """The call's worst case would go over the run's budget. Nothing was sent."""


class ModelServerError(RuntimeError):
    """The model API failed on its side (5xx, overloaded). Retried."""


class MalformedOutputError(RuntimeError):
    """The answer didn't match the request's output model. Retried."""


class ModelRefusedError(RuntimeError):
    """The model declined. Never retried: asking again wouldn't change the answer."""


class NeedsReviewError(RuntimeError):
    """Every attempt failed. The item is parked for a person to look at (PR 4)."""

    def __init__(self, reason: str):
        super().__init__(f"needs review after repeated {reason}")
        self.reason = reason


RETRYABLE = {
    TimeoutError: "timeout",
    ModelServerError: "server_error",
    MalformedOutputError: "malformed",
}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds before the 2nd attempt; doubles each time
    max_delay: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    jitter: Callable[[], float] = random.random  # 0..1

    def delay(self, attempt: int) -> float:
        """Exponential backoff with equal jitter: half fixed, half random, so many waiting
        callers don't all retry at the same moment."""
        ceiling = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        return ceiling / 2 + self.jitter() * ceiling / 2


DEFAULT_RETRY = RetryPolicy()


class Gateway:
    """One gateway per run: it holds the run's budget."""

    def __init__(
        self,
        client: ModelClient,
        audit: AuditLog,
        ledger: Ledger,
        budget: RunBudget,
        prices: dict[str, ModelPrices] | None = None,
        retry: RetryPolicy = DEFAULT_RETRY,
        allow: Iterable[tuple[str, int]] = (),  # the model API's host:port (PR 9)
        switch_folder: Callable[[], Path] = default_switch_folder,
    ):
        self.client = client
        self.audit = audit
        self.ledger = ledger
        self.budget = budget
        self.prices = prices if prices is not None else load_prices()
        self.retry = retry
        self.allow = tuple(allow)
        self._switch_folder = switch_folder

    def call(self, request: ModelRequest) -> ModelResponse:
        tool = f"model:{request.model}"

        def audit(outcome: str, reason: str, payload: object = None) -> None:
            self.audit.record(
                run_id=request.run_id,
                module=request.module,
                tool=tool,
                outcome=outcome,
                reason=reason,
                input_mac=self.audit.input_mac(payload),
            )

        if not (isinstance(request.system, Redacted) and isinstance(request.untrusted, Redacted)):
            audit("refused", "not_redacted")
            raise TypeError("the gateway only sends Redacted text; use redact()")
        prices = self.prices.get(request.model)
        if prices is None:
            audit("refused", "no_price")
            raise PriceError(f"no price for {request.model}")
        payload = build_payload(request)
        row = {
            "run_id": request.run_id,
            "module": request.module,
            "route": request.route,
            "model": request.model,
            "prompt_version": request.prompt_version,
            "prices_verified": prices.verified,
        }

        for attempt in range(1, self.retry.max_attempts + 1):
            # Checked before every attempt, so a switch set mid-run stops the next one.
            if not agents_allowed(self._switch_folder(), request.module):
                audit("blocked", "kill_switch")
                raise AgentsOffError("agents are switched off")
            worst = prices.worst_case_micro_usd(estimate_input_tokens(payload), request.max_tokens)
            if self.budget.would_exceed(worst):
                self.ledger.finish(self.ledger.start(**row, attempt=attempt), "budget_stopped")
                audit("blocked", "budget_exceeded")
                raise BudgetExceededError("this call could go over the run's budget")

            # Both rows before anything is sent; either raises if it can't be written.
            row_id = self.ledger.start(**row, attempt=attempt)
            audit("allowed", "ok", payload)
            try:
                with guarded_run(self.allow, on_refusal=lambda reason: audit("blocked", reason)):
                    response = self.client.complete(payload)
                cost = prices.cost_micro_usd(response.usage)
                self.budget.spent_micro_usd += cost
                if response.stop_reason == "refusal":
                    self.ledger.finish(row_id, "refused", response.usage, cost)
                    audit("failed", "refused")
                    raise ModelRefusedError("the model declined")
                if request.output_model is not None:
                    try:
                        request.output_model.model_validate(response.content)
                    except ValidationError:
                        self.ledger.finish(row_id, "malformed", response.usage, cost)
                        raise MalformedOutputError("the answer didn't match") from None
                self.ledger.finish(row_id, "ok", response.usage, cost)
                return response
            except tuple(RETRYABLE) as e:
                reason = RETRYABLE[type(e)]
                if reason != "malformed":  # a malformed answer was ledgered with its cost
                    # No answer, so no usage: the API may still have billed the request.
                    # The budget assumes the worst; the ledger's 0 means "unknown".
                    self.budget.spent_micro_usd += worst
                    self.ledger.finish(row_id, reason)
                audit("failed", reason)
                if attempt == self.retry.max_attempts:
                    raise NeedsReviewError(reason) from e
                self.retry.sleep(self.retry.delay(attempt))
            except ModelRefusedError:
                raise
            except Exception as e:
                # A guard refusal stopped the request before it left this machine; any other
                # error may have come after sending, so the budget assumes the worst.
                if not isinstance(e, NetworkGuardError):
                    self.budget.spent_micro_usd += worst
                self.ledger.finish(row_id, "failed")
                audit("failed", "model_error")
                raise
        raise AssertionError("unreachable")


def payload_text(payload: dict) -> str:
    """Everything a payload would send, as one string (for checks that nothing leaks)."""
    return json.dumps(payload, ensure_ascii=False)
