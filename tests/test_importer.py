import json
import subprocess
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlmodel import Session

from brain_dock import importer
from brain_dock.db import get_engine
from brain_dock.importer import (
    DEMO_JSON,
    REPO_ROOT,
    ImportFileError,
    load_applications,
    rebuild_db,
)
from brain_dock.models import Application, Company, Stage, StageEvent

from .conftest import SECRET


def entry(**overrides):
    base = {
        "company": "Acme Analytics",
        "role_title": "Solutions Engineer",
        "role_track": "fde",
        "applied_on": "2026-10-01",
    }
    return base | overrides


def write_file(tmp_path, applications):
    path = tmp_path / "applications.json"
    path.write_text(json.dumps({"applications": applications}))
    return path


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield engine
    engine.dispose()


def snapshot(engine):
    """Everything in the tracker tables, for before/after comparisons."""
    with Session(engine) as session:
        return {
            "companies": sorted(session.scalars(select(Company.name))),
            "applications": sorted(
                session.execute(select(Application.role_title, Application.current_stage)).all()
            ),
            "events": session.scalar(select(func.count()).select_from(StageEvent)),
        }


# --- Loading and validation -------------------------------------------------


def test_loads_a_valid_file(tmp_path):
    path = write_file(
        tmp_path,
        [entry(events=[{"stage": "screen", "happened_on": "2026-10-05", "note": "call"}])],
    )

    [app] = load_applications(path)

    assert app.company == "Acme Analytics"
    assert app.applied_on == date(2026, 10, 1)
    assert app.events[0].stage == Stage.screen


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_applications(tmp_path / "nope.json")


def test_invalid_json_reports_position_not_content(tmp_path):
    path = tmp_path / "applications.json"
    path.write_text('{"applications": [ {"company": "' + SECRET + '",, } ]}')

    with pytest.raises(ImportFileError) as caught:
        load_applications(path)

    assert "line 1" in str(caught.value)
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    ("bad_entry", "expected"),
    [
        (entry(role_track=SECRET), "entry 2, role_track: Input should be"),
        (entry(applied_on=SECRET), "entry 2, applied_on: Input should be a valid date"),
        (
            entry(events=[{"stage": SECRET, "happened_on": "2026-10-05"}]),
            "entry 2, events[1].stage: Input should be",
        ),
        (entry(company="   "), "entry 2, company: String should have at least 1 character"),
        (entry(**{SECRET: "x"}), "Extra inputs are not permitted"),
    ],
)
def test_errors_name_entry_and_field_but_never_the_value(tmp_path, bad_entry, expected):
    path = write_file(tmp_path, [entry(), bad_entry])

    with pytest.raises(ImportFileError) as caught:
        load_applications(path)

    message = str(caught.value)
    assert expected in message
    # The extra-field case names the key (a field name), so only check values for the others.
    if SECRET not in bad_entry:
        assert SECRET not in message


def test_missing_required_field(tmp_path):
    bad = entry()
    del bad["role_title"]
    path = write_file(tmp_path, [bad])

    with pytest.raises(ImportFileError, match="entry 1, role_title: Field required"):
        load_applications(path)


def test_explicit_applied_event_is_rejected(tmp_path):
    path = write_file(tmp_path, [entry(events=[{"stage": "applied", "happened_on": "2026-10-01"}])])

    with pytest.raises(ImportFileError, match=r"entry 1, events\[1\]\.stage: .*applied_on"):
        load_applications(path)


def test_event_before_applied_on_is_rejected(tmp_path):
    path = write_file(
        tmp_path,
        [entry(events=[{"stage": "screen", "happened_on": "2026-09-30"}])],
    )

    with pytest.raises(ImportFileError, match=r"entry 1: events\[1\] happened_on is before"):
        load_applications(path)


def test_every_problem_is_reported_at_once(tmp_path):
    path = write_file(tmp_path, [entry(role_track="x"), entry(applied_on="x")])

    with pytest.raises(ImportFileError) as caught:
        load_applications(path)

    assert len(caught.value.problems) == 2


# --- Rebuilding the database ------------------------------------------------


def test_rebuild_creates_rows_and_stages(engine, tmp_path):
    path = write_file(
        tmp_path,
        [
            entry(events=[{"stage": "screen", "happened_on": "2026-10-05"}]),
            entry(company="Globex Systems", role_title="Support Lead", role_track="support"),
        ],
    )

    counts = rebuild_db(engine, load_applications(path))

    assert (counts.companies, counts.applications, counts.events) == (2, 2, 3)
    assert snapshot(engine)["applications"] == [
        ("Solutions Engineer", Stage.screen),
        ("Support Lead", Stage.applied),
    ]


def test_companies_match_case_insensitively_after_trimming(engine, tmp_path):
    path = write_file(
        tmp_path,
        [
            entry(company="Acme Analytics"),
            entry(company="  acme analytics ", role_title="Support Engineer"),
        ],
    )

    counts = rebuild_db(engine, load_applications(path))

    assert counts.companies == 1
    assert snapshot(engine)["companies"] == ["Acme Analytics"]  # first spelling wins


def test_stored_company_name_is_trimmed_even_when_first(engine, tmp_path):
    path = write_file(
        tmp_path,
        [
            entry(company="  Acme Analytics \t"),
            entry(company="ACME ANALYTICS", role_title="Support Engineer"),
        ],
    )

    rebuild_db(engine, load_applications(path))

    assert snapshot(engine)["companies"] == ["Acme Analytics"]


def test_rebuilding_twice_gives_the_same_result(engine, tmp_path):
    entries = load_applications(write_file(tmp_path, [entry(), entry(company="Globex Systems")]))

    rebuild_db(engine, entries)
    first = snapshot(engine)
    rebuild_db(engine, entries, locked=False)

    assert snapshot(engine) == first


def test_rebuild_replaces_previous_rows(engine, tmp_path):
    rebuild_db(engine, load_applications(write_file(tmp_path, [entry(company="Old Co")])))

    rebuild_db(
        engine, load_applications(write_file(tmp_path, [entry(company="New Co")])), locked=False
    )

    assert snapshot(engine)["companies"] == ["New Co"]


def test_mid_insert_failure_leaves_the_database_unchanged(engine, tmp_path, monkeypatch):
    rebuild_db(engine, load_applications(write_file(tmp_path, [entry(company="Old Co")])))
    before = snapshot(engine)

    calls = 0

    def failing_record_stage(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated crash halfway through")
        return original(*args, **kwargs)

    original = importer.record_stage
    monkeypatch.setattr(importer, "record_stage", failing_record_stage)
    new_entries = load_applications(
        write_file(
            tmp_path,
            [
                entry(
                    company="New Co",
                    events=[
                        {"stage": "screen", "happened_on": "2026-10-05"},
                        {"stage": "interview", "happened_on": "2026-10-10"},
                    ],
                )
            ],
        )
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        rebuild_db(engine, new_entries, locked=False)

    assert calls == 2  # the crash happened after deletes and some inserts
    assert snapshot(engine) == before


def test_demo_file_is_valid_and_uses_fake_companies(engine):
    entries = load_applications(DEMO_JSON)
    counts = rebuild_db(engine, entries)

    assert counts.applications == len(entries) >= 5
    assert set(snapshot(engine)["companies"]) <= {
        "Acme Analytics",
        "Globex Systems",
        "Initech",
        "Hooli",
        "Pied Piper",
    }
    assert {a.events[-1].stage for a in entries if a.events} >= {
        Stage.offer,
        Stage.rejected,
        Stage.ghosted,
        Stage.withdrawn,
    }


# --- Command line -----------------------------------------------------------


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the command at temp files so tests never touch the real data/ folder."""
    real_json = tmp_path / "my_applications.json"
    real_db = tmp_path / "brain_dock.db"
    demo_db = tmp_path / "demo.db"
    monkeypatch.setattr(importer, "REAL_JSON", real_json)
    monkeypatch.setattr(importer, "REAL_DB", real_db)
    monkeypatch.setattr(importer, "DEMO_DB", demo_db)
    return real_json, real_db, demo_db


def test_demo_writes_only_to_the_demo_database(paths, capsys):
    _, real_db, demo_db = paths

    assert importer.main(["--demo"]) == 0

    assert demo_db.exists()
    assert not real_db.exists()
    assert "demo.db" in capsys.readouterr().out


def test_real_import_prints_counts_but_no_names(paths, capsys):
    real_json, real_db, _ = paths
    real_json.write_text(json.dumps({"applications": [entry(company=SECRET)]}))

    assert importer.main([]) == 0

    out = capsys.readouterr().out
    assert "Imported 1 applications at 1 companies (1 stage events)" in out
    assert SECRET not in out
    assert real_db.exists()


def test_missing_real_file_explains_what_to_do(paths, capsys):
    _, real_db, _ = paths

    assert importer.main([]) == 1

    assert "Copy demo/applications.json to data/my_applications.json" in capsys.readouterr().err
    assert not real_db.exists()


def test_invalid_file_imports_nothing_and_hides_values(paths, capsys):
    real_json, real_db, _ = paths
    real_json.write_text(json.dumps({"applications": [entry()]}))
    importer.main([])
    engine = get_engine(f"sqlite:///{real_db}")
    before = snapshot(engine)

    real_json.write_text(json.dumps({"applications": [entry(role_track=SECRET)]}))
    assert importer.main([]) == 1

    err = capsys.readouterr().err
    assert "Nothing imported" in err
    assert "entry 1, role_track" in err
    assert SECRET not in err
    assert snapshot(engine) == before
    engine.dispose()


# --- Privacy ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "data/my_applications.json",
        "data/brain_dock.db",
        "data/demo.db",
        "data/backups/applications-20261021-120000.json",
        "anything.db",
    ],
)
def test_personal_data_files_are_gitignored(path):
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT)

    assert result.returncode == 0, f"{path} is not gitignored"


@pytest.mark.parametrize("link", ["javascript:alert(1)", "data:text/html,x", "example.com"])
def test_non_http_links_are_rejected_without_echoing_them(tmp_path, link):
    path = write_file(tmp_path, [entry(link=link)])

    with pytest.raises(ImportFileError) as caught:
        load_applications(path)

    assert "entry 1, link: must be an http:// or https:// URL" in str(caught.value)
    assert link not in str(caught.value)


def test_https_link_is_accepted(tmp_path):
    [app] = load_applications(write_file(tmp_path, [entry(link="https://example.com/jobs/1")]))

    assert app.link == "https://example.com/jobs/1"


# --- Safety lock -------------------------------------------------------------


@pytest.fixture
def filled(engine, tmp_path):
    """A real (locked) database that already has one application."""
    rebuild_db(engine, load_applications(write_file(tmp_path, [entry(company="Old Co")])))
    return engine


def new_entries(tmp_path):
    return load_applications(write_file(tmp_path, [entry(company="New Co")]))


def test_lock_refuses_a_non_empty_database(filled, tmp_path):
    before = snapshot(filled)

    with pytest.raises(importer.DatabaseNotEmptyError, match="already has 1 applications") as e:
        rebuild_db(filled, new_entries(tmp_path))

    assert "Old Co" not in str(e.value)
    assert snapshot(filled) == before


def test_empty_database_needs_no_force_or_backup(engine, tmp_path):
    counts = rebuild_db(engine, new_entries(tmp_path), backup_dir=tmp_path / "backups")

    assert counts.backup is None
    assert not (tmp_path / "backups").exists()


def test_force_backs_up_completely_before_deleting(filled, tmp_path, monkeypatch):
    from brain_dock import export

    seen_at_backup_time = []
    real_write_backup = export.write_backup

    def spy(engine, backup_dir=None, now=None):
        backup = real_write_backup(engine, backup_dir, now)
        seen_at_backup_time.append(snapshot(engine)["companies"])  # backup is done here
        return backup

    monkeypatch.setattr(export, "write_backup", spy)

    counts = rebuild_db(filled, new_entries(tmp_path), force=True, backup_dir=tmp_path / "bk")

    assert seen_at_backup_time == [["Old Co"]]  # old data was still there when backed up
    assert json.loads(counts.backup.read_text())["applications"][0]["company"] == "Old Co"
    assert snapshot(filled)["companies"] == ["New Co"]


def test_failed_backup_aborts_without_wiping(filled, tmp_path, monkeypatch):
    from brain_dock import export

    def broken(*args, **kwargs):
        raise OSError("backup disk full (simulated)")

    monkeypatch.setattr(export, "write_backup", broken)
    before = snapshot(filled)

    with pytest.raises(OSError, match="backup disk full"):
        rebuild_db(filled, new_entries(tmp_path), force=True)

    assert snapshot(filled) == before


def test_demo_database_is_not_locked(paths):
    assert importer.main(["--demo"]) == 0
    assert importer.main(["--demo"]) == 0  # reloads without --force


def test_command_refuses_then_forces_with_a_backup(paths, capsys):
    from brain_dock import export

    real_json, real_db, _ = paths
    real_json.write_text(json.dumps({"applications": [entry(company=SECRET)]}))
    assert importer.main([]) == 0
    capsys.readouterr()

    assert importer.main([]) == 1
    err = capsys.readouterr().err
    assert "already has 1 applications. Nothing was changed." in err
    assert SECRET not in err

    assert importer.main(["--force"]) == 0
    out = capsys.readouterr().out
    assert "Backed up the previous data to data/backups/applications-" in out
    assert SECRET not in out
    [backup] = list(export.BACKUP_DIR.iterdir())
    assert SECRET in backup.read_text()  # the data is in the backup, just never printed


def test_command_reports_a_failed_backup(paths, capsys, monkeypatch):
    from brain_dock import export

    real_json, real_db, _ = paths
    real_json.write_text(json.dumps({"applications": [entry()]}))
    importer.main([])
    engine = get_engine(f"sqlite:///{real_db}")
    before = snapshot(engine)
    monkeypatch.setattr(export, "write_backup", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    capsys.readouterr()

    assert importer.main(["--force"]) == 1

    assert "Backup failed, so nothing was changed" in capsys.readouterr().err
    assert snapshot(engine) == before
    engine.dispose()
