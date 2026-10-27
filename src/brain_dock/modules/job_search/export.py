import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from brain_dock.core import db
from brain_dock.core.db import get_engine, is_at_head
from brain_dock.modules.job_search.importer import ImportFileError, load_applications
from brain_dock.modules.job_search.models import Application, creation_event, interested_event

# Backups live in the gitignored data/ folder.
BACKUP_DIR = db.REPO_ROOT / "data" / "backups"


class BackupError(RuntimeError):
    """The backup could not be written or didn't validate. No backup file was created."""


@dataclass(frozen=True)
class Backup:
    path: Path
    applications: int
    events: int


def export_applications(session: Session) -> dict:
    """Everything in the tracker, in the same format the importer reads."""
    applications = session.exec(
        select(Application)
        .options(selectinload(Application.company), selectinload(Application.events))
        .order_by(Application.applied_on, Application.id)
    ).all()

    exported = []
    for app in applications:
        events = sorted(app.events, key=lambda e: (e.happened_on, e.id))
        # The first "applied" event is the one create_application() adds from applied_on;
        # the importer recreates it, so it isn't listed.
        creation = creation_event(app)
        # Same for the "interested" event save_interested() adds from interested_on.
        saved = interested_event(app)
        entry = {
            "company": app.company.name,
            "role_title": app.role_title,
            "role_track": app.role_track.value,
        }
        if saved is not None:
            entry["interested_on"] = saved.happened_on.isoformat()
        if app.applied_on is not None:
            entry["applied_on"] = app.applied_on.isoformat()
        for field in ("link", "notes"):
            if getattr(app, field) is not None:
                entry[field] = getattr(app, field)
        if app.follow_up_on is not None:
            entry["follow_up_on"] = app.follow_up_on.isoformat()
        entry["events"] = [
            {"stage": e.stage.value, "happened_on": e.happened_on.isoformat()}
            | ({"note": e.note} if e.note is not None else {})
            for e in events
            if e is not creation and e is not saved
        ]
        exported.append(entry)
    return {"applications": exported}


def _final_path(backup_dir: Path, now: datetime) -> Path:
    base = f"applications-{now:%Y%m%d-%H%M%S}"
    path, n = backup_dir / f"{base}.json", 2
    while path.exists():  # never overwrite an earlier backup
        path, n = backup_dir / f"{base}-{n}.json", n + 1
    return path


def write_backup(
    engine: Engine, backup_dir: Path | None = None, now: datetime | None = None
) -> Backup:
    """Write a complete, validated backup, or nothing at all.

    The JSON goes to a temp file in the backup folder itself (same filesystem, so the
    rename is atomic), owner-only (0600), flushed to disk, and re-read with the importer's
    validation. Only then is it renamed into place. Any failure removes the temp file.
    """
    backup_dir = backup_dir or BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        data = export_applications(session)
    expected_apps = len(data["applications"])
    expected_events = sum(len(a["events"]) + 1 for a in data["applications"])

    fd, tmp_name = tempfile.mkstemp(dir=backup_dir, prefix=".tmp-", suffix=".json")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

        try:
            entries = load_applications(tmp)
        except ImportFileError as e:
            raise BackupError(f"The backup didn't pass validation: {e}") from None
        if len(entries) != expected_apps:
            raise BackupError("The backup didn't contain every application.")

        final = _final_path(backup_dir, now or datetime.now())
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return Backup(path=final, applications=expected_apps, events=expected_events)


def main() -> int:
    if not db.DB_PATH.exists():
        print("No database yet. Run: uv run python -m brain_dock.db", file=sys.stderr)
        return 1
    engine = get_engine()
    try:
        if not is_at_head(engine):
            print(
                "The database needs migrating. Run: uv run python -m brain_dock.db", file=sys.stderr
            )
            return 1
        backup = write_backup(engine)
    except (BackupError, OSError) as e:
        print(f"No backup written: {e}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"Exported {backup.applications} applications ({backup.events} stage events) "
        f"to data/backups/{backup.path.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
