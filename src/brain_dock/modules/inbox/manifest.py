"""Inbox: module #2 (ADR 0007), the first agent (ADR 0008)."""

from pathlib import Path

from brain_dock.core.modules import Manifest, NavEntry
from brain_dock.modules.inbox.routes import router
from brain_dock.modules.inbox.tools import AGENT_TOOLS

MODULE_DIR = Path(__file__).parent

manifest = Manifest(
    name="inbox",
    description="Job-alert emails, rules first, suggestions that wait for my approval.",
    home="/inbox",
    router=router,
    paths=("/inbox",),
    nav=(NavEntry("Inbox", "/inbox"),),
    tables=("inbox_email", "inbox_role", "inbox_role_source"),
    migrations=MODULE_DIR / "migrations",
    templates=MODULE_DIR / "templates",
    permissions=("storage",),
    agent_tools=AGENT_TOOLS,
)
