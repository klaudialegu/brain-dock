"""The LLM gateway (ADR 0008, design section 1): the only code that talks to a model.

Every call: text must be Redacted (plain strings are refused), the kill switches are
checked, an audit row is written before anything is sent (fail closed), and the client
runs inside the network guard with only the model API allowed. Retries, the ledger and
budgets come in PR 3c; the live client in PR 9.
"""

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from brain_dock.core.agents.audit import AuditLog
from brain_dock.core.agents.guard import guarded_run
from brain_dock.core.agents.killswitch import agents_allowed
from brain_dock.core.agents.passes import default_switch_folder
from brain_dock.core.agents.tools import AgentTool

# --- Redaction ---------------------------------------------------------------------------

_TOKEN = object()  # only redact() has it, so only redact() makes Redacted text

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_QUERY = re.compile(r"(https?://[^\s?#]+)\?[^\s#]*")
PHONE_CANDIDATE = re.compile(r"(?<![\w+])\+?\d[\d ().-]{6,}\d(?!\w)")
SIGNATURE = re.compile(r"^-- ?$.*", re.MULTILINE | re.DOTALL)  # the "-- " line and after
PHONE_MIN_DIGITS = 9  # dates (8 digits) and salaries stay; phone numbers go


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


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


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


# --- The gateway -------------------------------------------------------------------------


class AgentsOffError(RuntimeError):
    """A kill switch is set (or couldn't be checked). Nothing was sent."""


class Gateway:
    def __init__(
        self,
        client: ModelClient,
        audit: AuditLog,
        allow: Iterable[tuple[str, int]] = (),  # the model API's host:port (PR 9)
        switch_folder: Callable[[], Path] = default_switch_folder,
    ):
        self.client = client
        self.audit = audit
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
        if not agents_allowed(self._switch_folder(), request.module):
            audit("blocked", "kill_switch")
            raise AgentsOffError("agents are switched off")

        payload = build_payload(request)
        audit("allowed", "ok", payload)  # before anything is sent; raises if it can't
        try:
            with guarded_run(self.allow, on_refusal=lambda reason: audit("blocked", reason)):
                return self.client.complete(payload)
        except Exception:
            audit("failed", "model_error")
            raise


def payload_text(payload: dict) -> str:
    """Everything a payload would send, as one string (for checks that nothing leaks)."""
    return json.dumps(payload, ensure_ascii=False)
