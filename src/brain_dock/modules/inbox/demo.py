"""Load the synthetic alerts in demo/inbox/ into the demo database, so the triage page has
something to show: `uv run python -m brain_dock.modules.inbox.demo`.

Always data/demo.db, never the real database, whatever BRAIN_DOCK_DB says; and always the
fake thresholds in config.example.toml, passed explicitly (it's never a fallback for a
missing config.toml).
"""

import sys
from pathlib import Path

from brain_dock.core import db
from brain_dock.core.agents.audit import AuditLog, key_path_for, load_or_create_key
from brain_dock.core.agents.passes import Dispatcher, PassOffice
from brain_dock.core.agents.runs import Runner
from brain_dock.modules.inbox.agent import run_inbox

DEMO_EMAILS = db.REPO_ROOT / "demo" / "inbox"
EXAMPLE_CONFIG = db.REPO_ROOT / "config.example.toml"


class NoModelClient:
    """Rules-only runs make no model calls; if one ever tried, it fails here."""

    def complete(self, payload: dict):
        raise RuntimeError("rules-only run: no model calls")


def load_demo(path: Path) -> str:
    from brain_dock.modules.inbox.manifest import manifest  # not at import: manifest -> routes

    not_ready = "The demo database isn't ready. Run: uv run python -m brain_dock.importer --demo"
    if not path.exists():  # checked first: connecting would create an empty file
        return not_ready
    engine = db.get_engine(f"sqlite:///{path}")
    try:
        if not db.is_at_head(engine):
            return not_ready
        audit = AuditLog(engine, load_or_create_key(key_path_for(path)))
        office = PassOffice([manifest])
        folder = path.parent
        dispatcher = Dispatcher(office, audit, [manifest], lambda: folder)
        runner = Runner(
            engine, audit, office, dispatcher, NoModelClient(), switch_folder=lambda: folder
        )
        emails = [p.read_bytes() for p in sorted(DEMO_EMAILS.glob("*.eml"))]
        report = run_inbox(runner, emails, config_path=EXAMPLE_CONFIG)
    finally:
        engine.dispose()
    counts = ", ".join(f"{state} {n}" for state, n in sorted(report.states.items()))
    return f"Loaded {len(emails)} demo emails into {path.name}: {counts or 'nothing new'}"


def main() -> int:
    message = load_demo(db.DEMO_DB_PATH)
    print(message)
    return 0 if message.startswith("Loaded") else 1


if __name__ == "__main__":
    sys.exit(main())
