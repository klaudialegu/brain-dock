"""Capability passes and the dispatcher (ADR 0008, design section 2).

Every tool call an agent makes goes through Dispatcher.call() with the run's pass. The
pass lists exactly the tools its module declared; anything else is blocked. Every call is
audited before anything runs, and if the audit write fails, nothing runs (fail closed).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from brain_dock.core.agents.audit import AuditLog
from brain_dock.core.agents.tools import FORBIDDEN, AgentTool, Effect
from brain_dock.core.modules import Manifest


@dataclass(frozen=True)
class CapabilityPass:
    pass_id: str
    run_id: str
    module: str
    tools: frozenset[str]


class PassOffice:
    """Issues passes. Only a pass this office issued, unchanged, is honored: a pass a module
    builds itself, or one whose fields were changed after issue, is not."""

    def __init__(self, manifests: Sequence[Manifest]):
        self._manifests = {m.name: m for m in manifests}
        self._issued: dict[str, tuple[str, str, frozenset[str]]] = {}

    def issue(self, module: str, run_id: str) -> CapabilityPass:
        tools = frozenset(t.name for t in self._manifests[module].agent_tools)
        issued = CapabilityPass(uuid.uuid4().hex, run_id, module, tools)
        self._issued[issued.pass_id] = (run_id, module, tools)  # a copy, not the object
        return issued

    def honors(self, capability_pass: object) -> bool:
        if type(capability_pass) is not CapabilityPass:
            return False
        issued = self._issued.get(capability_pass.pass_id)
        fields = (capability_pass.run_id, capability_pass.module, capability_pass.tools)
        return issued is not None and issued == fields


@dataclass(frozen=True)
class ToolResult:
    """What the agent gets back. Errors are short and never echo the input."""

    ok: bool
    output: dict | None = None
    error: str | None = None


class Dispatcher:
    def __init__(self, office: PassOffice, audit: AuditLog, manifests: Sequence[Manifest]):
        self.office = office
        self.audit = audit
        self._tools: dict[tuple[str, str], AgentTool] = {
            (m.name, t.name): t for m in manifests for t in m.agent_tools
        }

    def call(self, capability_pass: CapabilityPass, tool_name: str, raw_input: dict) -> ToolResult:
        module = str(getattr(capability_pass, "module", ""))

        def audit(outcome: str, reason: str) -> None:
            # Raises AuditWriteError when the row can't be written; then nothing runs.
            self.audit.record(
                run_id=str(getattr(capability_pass, "run_id", "")),
                module=module,
                tool=tool_name,
                outcome=outcome,
                reason=reason,
                input_mac=self.audit.input_mac(raw_input),
            )

        if not self.office.honors(capability_pass):
            audit("blocked", "forged_pass")
            return ToolResult(False, error="This run has no valid pass.")
        if tool_name not in capability_pass.tools:
            elsewhere = any(name == tool_name for (_, name) in self._tools)
            audit("blocked", "other_module_tool" if elsewhere else "undeclared_tool")
            return ToolResult(False, error=f"The tool {tool_name!r} isn't on this run's pass.")

        tool = self._tools[(module, tool_name)]
        if tool.effect in FORBIDDEN:
            audit("blocked", "forbidden_effect")
            return ToolResult(False, error="This tool can't run in an agent run.")
        try:
            data = tool.input_model.model_validate(raw_input)
        except ValidationError:
            audit("refused", "invalid_input")
            return ToolResult(False, error="The input didn't match the tool's schema.")
        if tool.effect == Effect.write:
            # Writes wait for my approval; approvals arrive in harness PR 4.
            audit("refused", "write_needs_approval")
            return ToolResult(False, error="This change needs approval first.")

        audit("allowed", "ok")
        try:
            output = tool.handler(data)
        except Exception:
            audit("failed", "tool_error")
            return ToolResult(False, error="The tool failed.")
        return ToolResult(True, output=output)
