import json
import os
import stat
from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, select

from brain_dock.core import db
from brain_dock.core.db import get_engine, migrate
from brain_dock.modules.job_search import export
from brain_dock.modules.job_search.export import BackupError, export_applications, write_backup
from brain_dock.modules.job_search.importer import load_applications, rebuild_db
from brain_dock.modules.job_search.manifest import manifest as job_search
from brain_dock.modules.job_search.models import Application, Company, RoleTrack, Stage, StageEvent

NOW = datetime(2026, 10, 21, 12, 0, 0)

# Every column must be listed in exactly one of these two maps.
# A new model column fails test_every_column_is_exported_or_explained until it's added here,
# and to export_applications() if it holds data.
EXPORTED = {
    "company.name": "company",
    "application.role_title": "role_title",
    "application.role_track": "role_track",
    "application.applied_on": "applied_on",
    "application.link": "link",
    "application.notes": "notes",
    "application.follow_up_on": "follow_up_on",
    "stageevent.stage": "stage",
    "stageevent.happened_on": "happened_on",
    "stageevent.note": "note",
}
NOT_EXPORTED = {
    "company.id": "internal key, recreated on import",
    "application.id": "internal key, recreated on import",
    "application.company_id": "expressed by the company name",
    "application.current_stage": "recalculated from the events on import",
    "stageevent.id": "internal key; event order is kept by sorting",
    "stageevent.application_id": "expressed by nesting events under their application",
}

FULL_ENTRIES = [
    {
        "company": "Acme Analytics",
        "role_title": "Forward Deployed Engineer",
        "role_track": "fde",
        "applied_on": "2026-09-01",
        "link": "https://example.com/jobs/1",
        "notes": "Fake notes, with ünïcödé.",
        "follow_up_on": "2026-09-15",
        "events": [
            {"stage": "screen", "happened_on": "2026-09-05", "note": "Recruiter call"},
            {"stage": "interview", "happened_on": "2026-09-10", "note": "Same day, first"},
            {"stage": "rejected", "happened_on": "2026-09-10", "note": "Same day, second"},
        ],
    },
    {
        "company": "Acme Analytics",
        "role_title": "Support Lead",
        "role_track": "support",
        "applied_on": "2026-09-02",
        "events": [],
    },
    {
        "company": "Globex Systems",
        "role_title": "Solutions Engineer",
        "role_track": "other",
        "applied_on": "2026-10-01",
        "link": "http://example.com/jobs/2",
        "notes": "More fake notes",
        "follow_up_on": "2026-10-08",
        "events": [{"stage": "withdrawn", "happened_on": "2026-10-03", "note": "Fake reason"}],
    },
]


def engine_at(path):
    engine = get_engine(f"sqlite:///{path}")
    migrate(engine)
    return engine


@pytest.fixture
def full_db(tmp_path):
    """A database where every optional field is filled somewhere."""
    source = tmp_path / "full.json"
    source.write_text(json.dumps({"applications": FULL_ENTRIES}))
    engine = engine_at(tmp_path / "full.db")
    rebuild_db(engine, load_applications(source))
    yield engine
    engine.dispose()


def exported(engine):
    with Session(engine) as session:
        return export_applications(session)


def files_in(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# --- Export format -----------------------------------------------------------


def test_export_matches_the_import_format_exactly(full_db):
    assert exported(full_db) == {"applications": FULL_ENTRIES}


def test_round_trip_keeps_everything(full_db, tmp_path):
    backup = write_backup(full_db, tmp_path / "backups", now=NOW)
    restored = engine_at(tmp_path / "restored.db")
    rebuild_db(restored, load_applications(backup.path))

    assert exported(restored) == exported(full_db)
    with Session(full_db) as a, Session(restored) as b:
        stages = [
            sorted((x.role_title, x.current_stage) for x in s.exec(select(Application)))
            for s in (a, b)
        ]
    assert stages[0] == stages[1]
    restored.dispose()


def test_every_column_is_exported_or_explained():
    # The backup is job search's: its tables only (the core's audit log isn't exported).
    tables = [SQLModel.metadata.tables[name] for name in job_search.tables]
    columns = {f"{t.name}.{c.name}" for t in tables for c in t.columns}

    assert columns == set(EXPORTED) | set(NOT_EXPORTED)
    assert not set(EXPORTED) & set(NOT_EXPORTED)


def test_full_export_uses_every_exported_field(full_db):
    data = exported(full_db)["applications"]
    keys = {k for app in data for k in app} | {k for app in data for e in app["events"] for k in e}

    assert set(EXPORTED.values()) <= keys


def test_only_the_creation_applied_event_is_left_out(tmp_path):
    engine = engine_at(tmp_path / "x.db")
    with Session(engine) as session:
        company = Company(name="Acme Analytics")
        app = Application(
            company=company,
            role_title="Engineer",
            role_track=RoleTrack.fde,
            applied_on=date(2026, 10, 1),
        )
        session.add_all(
            [
                app,
                StageEvent(application=app, stage=Stage.applied, happened_on=date(2026, 10, 1)),
                StageEvent(application=app, stage=Stage.applied, happened_on=date(2026, 10, 2)),
            ]
        )
        session.commit()

    assert exported(engine)["applications"][0]["events"] == [
        {"stage": "applied", "happened_on": "2026-10-02"}
    ]
    engine.dispose()


# --- Writing a backup --------------------------------------------------------


def test_backup_is_written_with_counts_and_timestamped_name(full_db, tmp_path):
    backup = write_backup(full_db, tmp_path / "backups", now=NOW)

    assert backup.path.name == "applications-20261021-120000.json"
    assert (backup.applications, backup.events) == (3, 7)
    assert json.loads(backup.path.read_text()) == {"applications": FULL_ENTRIES}
    assert files_in(tmp_path / "backups") == [backup.path.name]  # no temp file left


def test_backup_file_is_owner_only(full_db, tmp_path):
    backup = write_backup(full_db, tmp_path / "backups", now=NOW)

    assert stat.S_IMODE(backup.path.stat().st_mode) == 0o600


def test_existing_backup_is_never_overwritten(full_db, tmp_path):
    first = write_backup(full_db, tmp_path / "backups", now=NOW)
    original = first.path.read_bytes()

    second = write_backup(full_db, tmp_path / "backups", now=NOW)

    assert second.path.name == "applications-20261021-120000-2.json"
    assert first.path.read_bytes() == original


def test_temp_file_is_in_the_backup_folder_and_renamed(full_db, tmp_path, monkeypatch):
    renames = []
    real_replace = os.replace

    def spy(src, dst):
        renames.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    backup = write_backup(full_db, tmp_path / "backups", now=NOW)

    [(src, dst)] = renames
    assert os.path.dirname(src) == os.path.dirname(dst) == str(tmp_path / "backups")
    assert os.path.basename(src).startswith(".tmp-")
    assert dst == str(backup.path)


def test_failure_while_writing_leaves_no_files(full_db, tmp_path, monkeypatch):
    def crash(*args, **kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "fsync", crash)

    with pytest.raises(OSError, match="disk full"):
        write_backup(full_db, tmp_path / "backups", now=NOW)
    assert files_in(tmp_path / "backups") == []


def test_failure_at_rename_leaves_no_files(full_db, tmp_path, monkeypatch):
    def crash(src, dst):
        raise OSError("rename failed (simulated)")

    monkeypatch.setattr(os, "replace", crash)

    with pytest.raises(OSError, match="rename failed"):
        write_backup(full_db, tmp_path / "backups", now=NOW)
    assert files_in(tmp_path / "backups") == []


def test_backup_that_fails_validation_is_not_kept(tmp_path):
    # A link the importer would reject, written straight to the database.
    engine = engine_at(tmp_path / "x.db")
    with Session(engine) as session:
        session.add(
            Application(
                company=Company(name="Acme Analytics"),
                role_title="Engineer",
                role_track=RoleTrack.fde,
                applied_on=date(2026, 10, 1),
                link="javascript:alert(1)",
            )
        )
        session.commit()

    with pytest.raises(BackupError, match="entry 1, link") as caught:
        write_backup(engine, tmp_path / "backups", now=NOW)
    assert "javascript" not in str(caught.value)
    assert files_in(tmp_path / "backups") == []
    engine.dispose()


def test_validation_runs_on_the_temp_file_before_the_rename(full_db, tmp_path, monkeypatch):
    order = []
    real_load, real_replace = export.load_applications, os.replace
    monkeypatch.setattr(
        export, "load_applications", lambda p: order.append(("validate", p.name)) or real_load(p)
    )
    monkeypatch.setattr(
        os,
        "replace",
        lambda s, d: order.append(("rename", os.path.basename(s))) or real_replace(s, d),
    )

    write_backup(full_db, tmp_path / "backups", now=NOW)

    (first, temp_name), (second, renamed) = order
    assert (first, second) == ("validate", "rename")
    assert temp_name == renamed and temp_name.startswith(".tmp-")


# --- Command line ------------------------------------------------------------
# The autouse fixture in conftest.py points db.DB_PATH and export.BACKUP_DIR at temp paths.


def test_export_command_prints_counts_not_names(full_db, tmp_path, monkeypatch, capsys):

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "full.db")

    assert export.main() == 0

    out = capsys.readouterr().out
    assert "Exported 3 applications (7 stage events) to data/backups/applications-" in out
    assert "Acme" not in out
    assert len(files_in(export.BACKUP_DIR)) == 1


def test_export_command_without_a_database(capsys):
    assert export.main() == 1
    assert "No database yet" in capsys.readouterr().err
