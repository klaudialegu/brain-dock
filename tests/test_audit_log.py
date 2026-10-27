"""The audit log (ADR 0008): keyed hashes instead of inputs, a local owner-only key,
append-only triggers that stop bugs, and a hash chain that detects tampering."""

import logging
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from brain_dock.core import db
from brain_dock.core.agents import audit
from brain_dock.core.agents.audit import (
    AuditEvent,
    AuditKey,
    AuditKeyError,
    AuditLog,
    canonical_json,
    key_path_for,
    load_or_create_key,
    verify_chain,
)
from brain_dock.core.db import REPO_ROOT, get_engine, migrate

from .conftest import SECRET

KEY = AuditKey(b"k" * 32)


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    migrate(engine)
    yield engine
    engine.dispose()


def write(log, n=1, tool="list_jobs"):
    for i in range(n):
        log.record(
            run_id="run-1",
            module="inbox",
            tool=tool,
            outcome="allowed",
            reason="ok",
            input_mac=log.input_mac({"n": i}),
        )


def raw(engine, sql):
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


# --- Keyed hashes and the key ---------------------------------------------------------


def test_audit_rows_hold_no_tool_input(engine):
    log = AuditLog(engine, KEY)

    log.record(
        run_id="run-1",
        module="inbox",
        tool="list_jobs",
        outcome="allowed",
        reason="ok",
        input_mac=log.input_mac({"company": SECRET}),
    )

    with engine.connect() as connection:
        dump = "\n".join(connection.connection.iterdump())
    assert "core_audit_event" in dump and "list_jobs" in dump  # the dump covers the row
    assert SECRET not in dump


def test_same_input_with_another_key_gives_another_hash():
    value = canonical_json({"company": "Acme Analytics"})

    assert KEY.mac(value) == AuditKey(b"k" * 32).mac(value)
    assert KEY.mac(value) != AuditKey(b"j" * 32).mac(value)


def test_key_is_made_once_owner_only_and_stays_out_of_git(tmp_path):
    path = key_path_for(tmp_path / "brain_dock.db")

    first = load_or_create_key(path)
    second = load_or_create_key(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    value = canonical_json({"x": 1})
    assert first.mac(value) == second.mac(value)  # created once, then read back
    # The real database's key lands in gitignored data/.
    real = key_path_for(REPO_ROOT / "data" / "brain_dock.db")
    ignored = subprocess.run(["git", "check-ignore", "-q", str(real)], cwd=REPO_ROOT, check=False)
    assert ignored.returncode == 0


def test_a_key_others_can_read_is_refused(tmp_path):
    path = key_path_for(tmp_path / "brain_dock.db")
    load_or_create_key(path)
    path.chmod(0o644)

    with pytest.raises(AuditKeyError, match="owner only"):
        load_or_create_key(path)


def test_key_never_shows_in_repr_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = key_path_for(tmp_path / "brain_dock.db")
    key = load_or_create_key(path)
    secret_hex = path.read_bytes().hex()

    shown = f"{key!r} {key!s}"

    assert "hidden" in shown and secret_hex not in shown
    assert secret_hex not in caplog.text


# --- Append-only and tamper-evident -----------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    ["UPDATE core_audit_event SET outcome = 'blocked'", "DELETE FROM core_audit_event"],
    ids=["update", "delete"],
)
def test_audit_log_is_append_only(engine, sql):
    write(AuditLog(engine, KEY))

    with pytest.raises(IntegrityError, match="append-only"):
        raw(engine, sql)


def test_an_untouched_chain_verifies(engine):
    log = AuditLog(engine, KEY)
    write(log, 3)

    report = verify_chain(engine, KEY)

    assert report.ok and report.entries == 3
    assert not verify_chain(engine, AuditKey(b"j" * 32)).ok  # and the key matters


@pytest.mark.parametrize(
    ("tamper", "problem"),
    [
        ("UPDATE core_audit_event SET outcome = 'blocked' WHERE id = 2", "entry 2 was changed"),
        ("DELETE FROM core_audit_event WHERE id = 2", "before entry 3 is missing"),
        ("DELETE FROM core_audit_event WHERE id = 1", "before entry 2 is missing"),
    ],
    ids=["edited", "deleted-middle", "deleted-first"],
)
def test_tampering_is_detected(engine, tamper, problem):
    write(AuditLog(engine, KEY), 3)
    # Someone with the database file: drop the trigger, then change the log with raw SQL.
    raw(engine, "DROP TRIGGER core_audit_event_no_update")
    raw(engine, "DROP TRIGGER core_audit_event_no_delete")
    raw(engine, tamper)

    report = verify_chain(engine, KEY)

    assert not report.ok and problem in report.problem


def test_a_row_slipped_in_without_the_key_is_detected(engine):
    write(AuditLog(engine, KEY), 2)
    assert verify_chain(engine, KEY).ok
    # A well-formed row that links to the chain, hashed with a key that isn't the real one.
    AuditLog(engine, AuditKey(b"j" * 32)).record(
        run_id="run-2", module="inbox", tool="x", outcome="allowed", reason="ok", input_mac="x"
    )

    report = verify_chain(engine, KEY)

    assert not report.ok and "entry 3 was changed" in report.problem


def test_the_chain_cannot_fork(engine):
    log = AuditLog(engine, KEY)
    write(log)

    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(
                AuditEvent(
                    at=datetime.now(UTC),
                    run_id="r",
                    module="m",
                    actor="agent",
                    tool="t",
                    outcome="allowed",
                    reason="ok",
                    input_mac="x",
                    prev_hash=audit.GENESIS,  # a second "first" row
                    row_hash="y",
                )
            )
            session.commit()


# --- The verify command -------------------------------------------------------------


@pytest.mark.parametrize("broken", [False, True], ids=["intact", "tampered"])
def test_verify_command(engine, capsys, monkeypatch, broken):
    path = Path(engine.url.database)
    monkeypatch.setattr(db, "DB_PATH", path)  # the command checks the database in use
    log = AuditLog(engine, load_or_create_key(key_path_for(path)))
    write(log, 2)
    if broken:
        raw(engine, "DROP TRIGGER core_audit_event_no_update")
        raw(engine, "UPDATE core_audit_event SET tool = 'other' WHERE id = 1")

    code = audit.main()

    out = capsys.readouterr()
    if broken:
        assert code == 1 and "BROKEN" in out.err and "entry 1 was changed" in out.err
    else:
        assert code == 0 and "Audit log OK: 2 entries" in out.out
    assert "list_jobs" not in out.out + out.err  # counts and positions, never contents
