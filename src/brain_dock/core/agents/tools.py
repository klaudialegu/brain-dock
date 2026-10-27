"""Agent tools a module declares in its manifest, and the policy every declaration must pass
(ADR 0008, docs/design/agent-harness.md section 2).

The policy is the first line: it keeps tools that send data out or delete anything out of
every manifest. The tool-name check below is a tripwire for mislabeled tools, not the
guarantee; the guarantee is the network guard in the gateway (harness PR 3).
"""

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from brain_dock.core.db import REPO_ROOT

DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"


class Effect(StrEnum):
    read = "read"  # looks at data
    draft = "draft"  # prepares something for me to look at; changes nothing I rely on
    write = "write"  # changes my data; only ever runs after my approval
    # Declarable so the policy can name and refuse them; forbidden without an ADR exception.
    outbound = "outbound"  # sends data off this machine (email, web requests, uploads)
    delete = "delete"  # removes data


FORBIDDEN = frozenset({Effect.outbound, Effect.delete})

# (module, tool) -> the ADR that allows it, as a file name in docs/decisions/. The ADR must
# be Accepted. Empty: no module may send data out or delete anything.
EXCEPTIONS: dict[tuple[str, str], str] = {}

# Words in a tool name that mean it sends data out or deletes; a tool named with one of them
# must declare that effect (and so needs an exception). Names are snake_case, so a word
# can't hide inside camelCase.
OUTBOUND_WORDS = frozenset(
    {"send", "email", "mail", "smtp", "http", "fetch", "request", "upload", "webhook",
     "notify", "publish", "share", "sms", "slack"}
)  # fmt: skip
DELETE_WORDS = frozenset(
    {"delete", "remove", "drop", "purge", "erase", "destroy", "wipe", "truncate", "unlink"}
)
NAME = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")


@dataclass(frozen=True)
class AgentTool:
    name: str  # snake_case, unique within its module
    description: str
    input_model: type[BaseModel]  # what the agent must send; checked before the tool runs
    effect: Effect
    handler: Callable[[BaseModel], dict]


def adr_status(path: Path) -> str | None:
    """The **Status:** of an ADR file, or None when the file or the line is missing."""
    if not path.is_file():
        return None
    match = re.search(r"^\*\*Status:\*\*\s*(.+?)\s*$", path.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def tool_policy_problems(
    module: str,
    tools: Sequence[AgentTool],
    exceptions: Mapping[tuple[str, str], str] = EXCEPTIONS,
    decisions_dir: Path = DECISIONS_DIR,
) -> list[str]:
    """Everything wrong with a module's tool declarations; empty means they pass."""
    problems = []
    for name, count in Counter(t.name for t in tools).items():
        if count > 1:
            problems.append(f"{module}.{name}: declared {count} times")
    for tool in tools:
        where = f"{module}.{tool.name}"
        if not NAME.fullmatch(tool.name):
            problems.append(f"{where}: tool names must be snake_case")
            continue
        words = set(tool.name.split("_"))
        if words & OUTBOUND_WORDS and tool.effect != Effect.outbound:
            problems.append(
                f"{where}: the name says it sends data out, but effect is {tool.effect}"
            )
        if words & DELETE_WORDS and tool.effect != Effect.delete:
            problems.append(f"{where}: the name says it deletes, but effect is {tool.effect}")
        if tool.effect in FORBIDDEN:
            adr = exceptions.get((module, tool.name))
            if adr is None:
                problems.append(f"{where}: {tool.effect} tools need an ADR exception")
            elif adr_status(decisions_dir / adr) != "Accepted":
                problems.append(f"{where}: exception {adr} must be an Accepted ADR")
    return problems
