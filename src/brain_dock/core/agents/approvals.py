"""Approvals (ADR 0008, design section 4; harness PR 4b): an agent's write waits for me.

A write tool call becomes a pending approval holding the exact input and its HMAC. Only
approve() runs it, outside any agent run, at most once:
- it re-checks the kill switches and refuses if the stored input no longer matches the HMAC
  recorded when the approval was made (so what runs is exactly what I approved);
- it marks the approval "executing" and commits that before the tool runs, then "executed"
  or "failed" after; on restart, one still "executing" is parked for review and never
  rerun, because the tool may or may not have run (park_interrupted, called at startup);
- the tool runs inside the network guard, and every decision is audited as "human".
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlmodel import Session, select

from brain_dock.core.agents.audit import AuditKey, AuditLog, canonical_json
from brain_dock.core.agents.guard import NetworkGuardError, guarded_run, run_active
from brain_dock.core.agents.killswitch import agents_allowed
from brain_dock.core.agents.run_tables import (
    APPROVED,
    NEEDS_REVIEW,
    PENDING_APPROVAL,
    REJECTED,
    Approval,
    WorkItem,
)
from brain_dock.core.agents.tools import AgentTool
from brain_dock.core.modules import Manifest

REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")  # e.g. "not_a_fit"; never free text


# A decided approval moves its work item out of pending_approval (harness PR 4c).
ITEM_STATE_AFTER = {
    "executed": APPROVED,
    "rejected": REJECTED,
    "failed": NEEDS_REVIEW,
    "needs_review": NEEDS_REVIEW,  # input_changed, invalid_input, interrupted
}


def _now() -> datetime:
    return datetime.now(UTC)


def _settle_item(session: Session, approval: Approval) -> None:
    """Moves the approval's item on, in the caller's commit, so the decision and the item
    never disagree. Only an item of the same module still waiting in pending_approval."""
    to_state = ITEM_STATE_AFTER.get(approval.status)
    if to_state is None or approval.item_id is None:
        return
    item = session.get(WorkItem, approval.item_id)
    if item is None or item.module != approval.module or item.state != PENDING_APPROVAL:
        return
    item.state = to_state
    item.reason = approval.reason
    item.updated_at = _now()
    session.add(item)


def create_approval(
    engine: Engine,
    key: AuditKey,
    *,
    run_id: str,
    module: str,
    item_id: int | None,
    tool: str,
    raw_input: dict,
) -> Approval:
    """Called by the dispatcher for a write tool. Stores the exact input and its HMAC."""
    text = canonical_json(raw_input).decode()
    with Session(engine) as session:
        approval = Approval(
            run_id=run_id,
            module=module,
            item_id=item_id,
            tool=tool,
            input_json=text,
            input_mac=key.mac(text.encode()),
            status="pending",
            created_at=_now(),
        )
        session.add(approval)
        session.commit()
        session.refresh(approval)
        return approval


@dataclass(frozen=True)
class ApprovalResult:
    ok: bool
    status: str  # the approval's status afterwards
    output: dict | None = None
    error: str | None = None


class Approvals:
    def __init__(
        self,
        engine: Engine,
        audit: AuditLog,
        manifests: Sequence[Manifest],
        switch_folder: Callable[[], Path],
    ):
        self.engine = engine
        self.audit = audit
        self._switch_folder = switch_folder
        self._tools: dict[tuple[str, str], AgentTool] = {
            (m.name, t.name): t for m in manifests for t in m.agent_tools
        }

    def _audit(self, approval: Approval | None, outcome: str, reason: str) -> None:
        self.audit.record(
            run_id=approval.run_id if approval else "",
            module=approval.module if approval else "",
            tool=approval.tool if approval else "",
            outcome=outcome,
            reason=reason,
            input_mac=approval.input_mac if approval else self.audit.input_mac(None),
            actor="human",
        )

    def _set(self, approval_id: int, **changes) -> Approval:
        with Session(self.engine) as session:
            approval = session.get(Approval, approval_id)
            for name, value in changes.items():
                setattr(approval, name, value)
            _settle_item(session, approval)
            session.commit()
            session.refresh(approval)
            return approval

    def _load_pending(self, approval_id: int) -> tuple[Approval | None, ApprovalResult | None]:
        """The approval if it can be decided now, or the refusal to return instead."""
        if run_active():
            self._audit(None, "blocked", "agent_cannot_approve")
            return None, ApprovalResult(False, "", error="Approvals happen outside agent runs.")
        with Session(self.engine) as session:
            approval = session.get(Approval, approval_id)
        if approval is None:
            return None, ApprovalResult(False, "", error="No such approval.")
        if approval.status != "pending":
            self._audit(approval, "refused", "not_pending")
            return None, ApprovalResult(False, approval.status, error="Already decided.")
        return approval, None

    def approve(self, approval_id: int) -> ApprovalResult:
        approval, refusal = self._load_pending(approval_id)
        if refusal is not None:
            return refusal
        if not agents_allowed(self._switch_folder(), approval.module):
            self._audit(approval, "blocked", "kill_switch")
            return ApprovalResult(False, "pending", error="Agents are switched off.")
        tool = self._tools.get((approval.module, approval.tool))
        if tool is None:  # the module is off or the tool is gone: try again later
            self._audit(approval, "refused", "unknown_tool")
            return ApprovalResult(False, "pending", error="That tool isn't available now.")
        if self.audit.key.mac(approval.input_json.encode()) != approval.input_mac:
            self._set(approval_id, status="needs_review", reason="input_changed")
            self._audit(approval, "refused", "input_changed")
            return ApprovalResult(
                False, "needs_review", error="The input changed since it was approved."
            )
        try:
            data = tool.input_model.model_validate(json.loads(approval.input_json))
        except (ValidationError, ValueError):
            self._set(approval_id, status="needs_review", reason="invalid_input")
            self._audit(approval, "refused", "invalid_input")
            return ApprovalResult(False, "needs_review", error="The input isn't valid anymore.")

        self._audit(approval, "allowed", "approved")  # before anything runs; raises if it can't
        # Committed before the tool runs: a crash from here on leaves "executing", which is
        # parked at the next startup, never run again.
        self._set(approval_id, status="executing", decided_at=_now(), decided_by="human")
        try:
            with guarded_run(on_refusal=lambda reason: self._audit(approval, "blocked", reason)):
                output = tool.handler(data)
        except NetworkGuardError:
            self._set(approval_id, status="failed", reason="guard_refused")
            self._audit(approval, "failed", "guard_refused")
            return ApprovalResult(False, "failed", error="The tool tried to reach outside.")
        except Exception:
            self._set(approval_id, status="failed", reason="tool_error")
            self._audit(approval, "failed", "tool_error")
            return ApprovalResult(False, "failed", error="The tool failed.")
        self._set(approval_id, status="executed")
        self._audit(approval, "executed", "ok")
        return ApprovalResult(True, "executed", output=output)

    def reject(self, approval_id: int, reason: str) -> ApprovalResult:
        if not REASON_CODE.fullmatch(reason):
            raise ValueError("a rejection reason is a short code like 'not_a_fit', not free text")
        approval, refusal = self._load_pending(approval_id)
        if refusal is not None:
            return refusal
        self._set(
            approval_id, status="rejected", reason=reason, decided_at=_now(), decided_by="human"
        )
        self._audit(approval, "rejected", reason)
        return ApprovalResult(True, "rejected")


def park_interrupted(engine: Engine, audit_for: Callable[[], AuditLog]) -> int:
    """At startup: an approval still "executing" was cut off mid-run. The tool may or may
    not have run, so it's parked for review and never rerun. Returns how many."""
    with Session(engine) as session:
        cut_off = session.exec(select(Approval).where(Approval.status == "executing")).all()
        if not cut_off:
            return 0
        audit = audit_for()  # loaded only when needed
        for approval in cut_off:
            approval.status = "needs_review"
            approval.reason = "interrupted"
            session.add(approval)
            audit.record(
                run_id=approval.run_id,
                module=approval.module,
                tool=approval.tool,
                outcome="parked",
                reason="interrupted",
                input_mac=approval.input_mac,
                actor="system",
            )
        # After the audit rows: loading an item flushes, and the session would then hold
        # SQLite's write lock while the audit log writes on its own connection.
        for approval in cut_off:
            _settle_item(session, approval)
        session.commit()
        return len(cut_off)
