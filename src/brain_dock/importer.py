import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import Engine, delete, func, select
from sqlmodel import Session

from brain_dock.db import DB_PATH, get_engine, migrate
from brain_dock.models import (
    Application,
    Company,
    RoleTrack,
    Stage,
    StageEvent,
    create_application,
    record_stage,
)
from brain_dock.queries import safe_link

REPO_ROOT = Path(__file__).parents[2]
REAL_JSON = REPO_ROOT / "data" / "my_applications.json"
REAL_DB = DB_PATH
DEMO_JSON = REPO_ROOT / "demo" / "applications.json"
DEMO_DB = REPO_ROOT / "data" / "demo.db"


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Stage
    happened_on: date
    note: str | None = None

    @field_validator("stage")
    @classmethod
    def not_applied(cls, stage: Stage) -> Stage:
        if stage == Stage.applied:
            raise ValueError('"applied" comes from applied_on; don\'t list it as an event')
        return stage


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company: str = Field(min_length=1)
    role_title: str = Field(min_length=1)
    role_track: RoleTrack
    applied_on: date
    link: str | None = None
    notes: str | None = None
    follow_up_on: date | None = None
    events: list[EventIn] = []

    @field_validator("link")
    @classmethod
    def http_link_only(cls, link: str | None) -> str | None:
        if link is not None and safe_link(link) is None:
            raise ValueError("must be an http:// or https:// URL")
        return link

    @model_validator(mode="after")
    def events_not_before_applied(self) -> "ApplicationIn":
        for i, event in enumerate(self.events, start=1):
            if event.happened_on < self.applied_on:
                raise ValueError(f"events[{i}] happened_on is before applied_on")
        return self


class ApplicationsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applications: list[ApplicationIn]


class ImportFileError(ValueError):
    """The file can't be imported. Messages never include values from the file."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class ImportCounts:
    companies: int
    applications: int
    events: int
    backup: Path | None = None  # set when --force backed up existing data first


class DatabaseNotEmptyError(RuntimeError):
    """The database already has applications, and the import would wipe them."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(
            f"The database already has {count} applications. Nothing was changed. "
            "Back them up with `uv run python -m brain_dock.export`, or pass --force "
            "(which writes a backup first)."
        )


def _describe(error: dict) -> str:
    # Uses only the location and Pydantic's message, never error["input"],
    # so personal values from the file can't end up in the terminal.
    loc = list(error["loc"])
    parts = []
    if loc[:1] == ["applications"] and len(loc) > 1 and isinstance(loc[1], int):
        parts.append(f"entry {loc[1] + 1}")
        loc = loc[2:]
    field = ""
    for item in loc:
        field += f"[{item + 1}]" if isinstance(item, int) else f"{'.' if field else ''}{item}"
    if field:
        parts.append(field)
    reason = error["msg"].removeprefix("Value error, ")
    return f"{', '.join(parts) or 'file'}: {reason}"


def load_applications(path: Path) -> list[ApplicationIn]:
    """Read and validate the whole file before anything touches the database."""
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ImportFileError([f"not valid JSON (line {e.lineno}, column {e.colno})"]) from None
    try:
        return ApplicationsFile.model_validate(raw).applications
    except ValidationError as e:
        raise ImportFileError([_describe(err) for err in e.errors()]) from None


def company_key(name: str) -> str:
    return name.strip().casefold()


def rebuild_db(
    engine: Engine,
    entries: list[ApplicationIn],
    *,
    locked: bool = True,
    force: bool = False,
    backup_dir: Path | None = None,
) -> ImportCounts:
    """Replace all tracker rows with the entries, in one transaction: all or nothing.

    locked (the default) refuses to wipe a database that already has applications,
    unless force is set; then a complete, validated backup is written first, and if
    that fails nothing is deleted. Only the disposable demo database runs unlocked.
    """
    # Imported here because export.py imports load_applications from this module.
    from brain_dock.export import write_backup

    migrate(engine)
    backup = None
    if locked:
        with Session(engine) as session:
            existing = session.scalar(select(func.count()).select_from(Application))
        if existing:
            if not force:
                raise DatabaseNotEmptyError(existing)
            backup = write_backup(engine, backup_dir).path  # raises before any delete

    with Session(engine) as session, session.begin():
        # Children first, so foreign keys are never left pointing at nothing.
        session.execute(delete(StageEvent))
        session.execute(delete(Application))
        session.execute(delete(Company))

        companies: dict[str, Company] = {}
        for entry in entries:
            key = company_key(entry.company)
            if key not in companies:
                companies[key] = Company(name=entry.company)
                session.add(companies[key])
            application = create_application(
                session,
                companies[key],
                entry.role_title,
                entry.role_track,
                entry.applied_on,
                link=entry.link,
                notes=entry.notes,
                follow_up_on=entry.follow_up_on,
            )
            for event in entry.events:
                record_stage(session, application, event.stage, event.happened_on, event.note)

        return ImportCounts(
            companies=session.scalar(select(func.count()).select_from(Company)),
            applications=session.scalar(select(func.count()).select_from(Application)),
            events=session.scalar(select(func.count()).select_from(StageEvent)),
            backup=backup,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brain_dock.importer",
        description="Rebuild the database from a JSON file of applications.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="load the fake demo data into data/demo.db (never the real database)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a database that already has applications (writes a backup first)",
    )
    args = parser.parse_args(argv)
    source, target = (DEMO_JSON, DEMO_DB) if args.demo else (REAL_JSON, REAL_DB)

    try:
        entries = load_applications(source)
    except FileNotFoundError:
        print(f"{source.name} not found.", file=sys.stderr)
        if not args.demo:
            print(
                "Copy demo/applications.json to data/my_applications.json and fill it in.",
                file=sys.stderr,
            )
        return 1
    except ImportFileError as e:
        print(f"Nothing imported. Fix {source.name}:", file=sys.stderr)
        for problem in e.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    # Deferred for the same reason as in rebuild_db.
    from brain_dock.export import BackupError

    engine = get_engine(f"sqlite:///{target}")
    try:
        counts = rebuild_db(engine, entries, locked=not args.demo, force=args.force)
    except DatabaseNotEmptyError as e:
        print(str(e), file=sys.stderr)
        return 1
    except (BackupError, OSError) as e:
        print(f"Backup failed, so nothing was changed: {e}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    if counts.backup:
        print(f"Backed up the previous data to data/backups/{counts.backup.name}")
    print(
        f"Imported {counts.applications} applications at {counts.companies} companies "
        f"({counts.events} stage events) into {target.parent.name}/{target.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
