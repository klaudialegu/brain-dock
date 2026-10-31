"""Shared helpers for the inbox tests: fake thresholds, the synthetic fixtures, a runner."""

from pathlib import Path

from sqlmodel import Session, select

from brain_dock import registry
from brain_dock.core.agents.audit import AuditKey, AuditLog
from brain_dock.core.agents.gateway import ScriptedClient
from brain_dock.core.agents.passes import Dispatcher, PassOffice
from brain_dock.core.agents.runs import Runner
from brain_dock.core.db import get_engine, migrate

FIXTURES = Path(__file__).parent / "fixtures" / "inbox"

# Fake thresholds, never real ones. Distinctive, so tests can prove they never leak.
FAKE_CONFIG = """\
[inbox]
locations = ["remote", "Example City"]
seniority = ["senior", "staff"]
salary_floor = 150000
currency = "USD"
"""
FAKE_CITY = "Example City"
FAKE_FLOOR = "150000"


def write_config(folder: Path, text: str = FAKE_CONFIG) -> Path:
    path = folder / "config.toml"
    path.write_text(text)
    return path


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def all_fixtures() -> list[bytes]:
    return [p.read_bytes() for p in sorted(FIXTURES.glob("*.eml"))]


def alert(*blocks: str, message_id: str = "<t-1@jobs.example.com>") -> str:
    """A synthetic alert email made of role blocks ("Field: value" lines)."""
    body = "\n---\n".join(blocks)
    return (
        "From: alerts@jobs.example.com\n"
        f"Message-ID: {message_id}\n"
        "X-Synthetic: true\n"
        "Content-Type: text/plain; charset=utf-8\n\n"
        f"{body}\n"
    )


def role_block(
    title="Senior Forward Deployed Engineer",
    company="Example Corp",
    location="Remote",
    salary="USD 160,000 - 190,000 per year",
    link="https://jobs.example.com/view/1",
) -> str:
    lines = [f"Role: {title}", f"Company: {company}", f"Location: {location}"]
    lines += [f"Salary: {salary}", f"Link: {link}"]
    return "\n".join(lines)


KEY = AuditKey(b"k" * 32)
INBOX = registry.INSTALLED["inbox"]


def migrate_app_db() -> None:
    """The test's stand-in for the app database (conftest patches db.DB_PATH); approvals
    run accept_suggestion against it."""
    engine = get_engine()
    migrate(engine)
    engine.dispose()


def make_runner(folder: Path):
    engine = get_engine()
    audit = AuditLog(engine, KEY)
    office = PassOffice([INBOX])
    dispatcher = Dispatcher(office, audit, [INBOX], lambda: folder)
    runner = Runner(
        engine, audit, office, dispatcher, ScriptedClient([]), switch_folder=lambda: folder
    )
    return runner, engine


def run_emails(folder: Path, emails):
    """One rules-only run over these emails; returns the stored roles."""
    from brain_dock.modules.inbox.agent import run_inbox
    from brain_dock.modules.inbox.models import InboxRole

    migrate_app_db()
    runner, engine = make_runner(folder)
    run_inbox(runner, emails, config_path=write_config(folder))
    with Session(engine) as session:
        return session.exec(select(InboxRole)).all()


def run_fixtures(folder: Path):
    return run_emails(folder, all_fixtures())
