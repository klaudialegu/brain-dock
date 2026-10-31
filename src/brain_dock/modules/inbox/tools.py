"""The inbox's agent tools. Its one write, accept_suggestion, only marks a role accepted in
the inbox's own table (ADR 0011): nothing is written outside the inbox. It never runs inside
an agent run; the dispatcher turns the call into a pending approval, and approve() runs it.
"""

from pydantic import BaseModel
from sqlmodel import Session

from brain_dock.core import db
from brain_dock.core.agents.tools import AgentTool, Effect
from brain_dock.modules.inbox.models import InboxRole


class AcceptSuggestion(BaseModel):
    suggestion_id: int  # write inputs are ids, never free text (tool policy)


def accept_suggestion(data: AcceptSuggestion) -> dict:
    engine = db.get_engine()  # the app's database; approve() runs outside any request
    try:
        with Session(engine) as session:
            role = session.get(InboxRole, data.suggestion_id)
            if role is None or role.status != "suggested":
                raise ValueError("only a suggested role can be accepted")
            role.status = "accepted"
            session.add(role)
            session.commit()
    finally:
        engine.dispose()
    return {"accepted": data.suggestion_id}


AGENT_TOOLS = (
    AgentTool(
        "accept_suggestion",
        "Mark a suggested role as accepted (inbox data only).",
        AcceptSuggestion,
        Effect.write,
        accept_suggestion,
    ),
)
