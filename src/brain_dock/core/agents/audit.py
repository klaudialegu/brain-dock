"""The audit log (ADR 0008): one row per tool call an agent tries, allowed or not.

- No inputs are stored, only an HMAC-SHA256 of them, with a local key (see load_or_create_key).
- Append-only: database triggers refuse UPDATE and DELETE. That stops bugs, not someone
  with the database file and a SQL prompt.
- Tamper-evident: each row holds the previous row's hash, and its own hash is an HMAC over
  its fields. verify_chain() detects a row that was changed, removed or slipped in by
  anyone without the key. Limits: removing the newest rows can't be detected by the chain
  alone, and the key lives on the same disk as the database.
"""

import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DDL, Engine, event
from sqlmodel import Field, Session, SQLModel, select

GENESIS = "0" * 64  # the "previous hash" of the first row
KEY_BYTES = 32
APPEND_ONLY_SQL = (
    "CREATE TRIGGER core_audit_event_no_update BEFORE UPDATE ON core_audit_event "
    "BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END",
    "CREATE TRIGGER core_audit_event_no_delete BEFORE DELETE ON core_audit_event "
    "BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END",
)


class AuditEvent(SQLModel, table=True):
    __tablename__ = "core_audit_event"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime  # timezone-aware, stored as UTC
    run_id: str = Field(index=True)
    module: str
    actor: str  # "agent" for now; approvals (PR 4) add "human"
    tool: str
    outcome: str  # allowed, blocked, refused, failed
    reason: str  # a short code, never details of the input
    input_mac: str  # HMAC-SHA256 of the input; the input itself is never stored
    # Each previous hash is used once, so the chain can't fork.
    prev_hash: str = Field(unique=True, index=True)
    row_hash: str


# create_all (test databases) gets the same triggers as migration core_0001.
for _sql in APPEND_ONLY_SQL:
    event.listen(AuditEvent.__table__, "after_create", DDL(_sql))


class AuditKeyError(RuntimeError):
    """The audit key file is missing, unreadable, the wrong size, or readable by others."""


class AuditWriteError(RuntimeError):
    """An audit row couldn't be written. The action it described doesn't happen."""


class AuditKey:
    """The local HMAC key. Its bytes never appear in repr, str or logs."""

    __slots__ = ("_key",)

    def __init__(self, key: bytes):
        if len(key) != KEY_BYTES:
            raise AuditKeyError(f"the audit key must be {KEY_BYTES} bytes")
        self._key = key

    def mac(self, data: bytes) -> str:
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def __repr__(self) -> str:
        return "AuditKey(<hidden>)"

    __str__ = __repr__


def canonical_json(value) -> bytes:
    """One byte string per value: sorted keys, no spaces, so equal inputs hash equally."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode()


def key_path_for(db_path: Path) -> Path:
    """The key sits next to its database (so in gitignored data/ for the real one)."""
    return db_path.with_name(db_path.name + ".audit-key")


def load_or_create_key(path: Path) -> AuditKey:
    """Read the key, or create it on first use: random, owner-only, written once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return read_key(path)
    key = secrets.token_bytes(KEY_BYTES)
    with os.fdopen(fd, "wb") as file:
        file.write(key)
    return AuditKey(key)


def read_key(path: Path) -> AuditKey:
    if not path.is_file():
        raise AuditKeyError("the audit key file is missing")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AuditKeyError("the audit key file must be readable by its owner only (chmod 600)")
    return AuditKey(path.read_bytes())


def _row_fields(row: AuditEvent) -> dict:
    return {
        "at": row.at.isoformat(),
        "run_id": row.run_id,
        "module": row.module,
        "actor": row.actor,
        "tool": row.tool,
        "outcome": row.outcome,
        "reason": row.reason,
        "input_mac": row.input_mac,
        "prev_hash": row.prev_hash,
    }


class AuditLog:
    """Writes audit rows, each in its own committed transaction, so a run that fails
    later can't take its audit rows with it."""

    def __init__(self, engine: Engine, key: AuditKey, clock: Callable[[], datetime] | None = None):
        self.engine = engine
        self.key = key
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()

    def input_mac(self, value) -> str:
        return self.key.mac(canonical_json(value))

    def record(
        self,
        *,
        run_id: str,
        module: str,
        tool: str,
        outcome: str,
        reason: str,
        input_mac: str,
        actor: str = "agent",
    ) -> AuditEvent:
        try:
            with self._lock, Session(self.engine) as session:
                last = session.exec(
                    select(AuditEvent.row_hash).order_by(AuditEvent.id.desc()).limit(1)
                ).first()
                row = AuditEvent(
                    at=self._clock(),
                    run_id=run_id,
                    module=module,
                    actor=actor,
                    tool=tool,
                    outcome=outcome,
                    reason=reason,
                    input_mac=input_mac,
                    prev_hash=last or GENESIS,
                    row_hash="",
                )
                row.row_hash = self.key.mac(canonical_json(_row_fields(row)))
                session.add(row)
                session.commit()
                session.refresh(row)
                return row
        except Exception as e:  # fail closed: the caller must not go ahead
            raise AuditWriteError("couldn't write the audit log") from e


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    entries: int
    problem: str | None = None


def verify_chain(engine: Engine, key: AuditKey) -> ChainReport:
    """Walk the chain from the first row. Reports where it breaks, never row contents."""
    expected_prev = GENESIS
    count = 0
    with Session(engine) as session:
        for row in session.exec(select(AuditEvent).order_by(AuditEvent.id)):
            count += 1
            if row.prev_hash != expected_prev:
                return ChainReport(
                    False, count, f"an entry before entry {row.id} is missing or was changed"
                )
            if not hmac.compare_digest(row.row_hash, key.mac(canonical_json(_row_fields(row)))):
                return ChainReport(False, count, f"entry {row.id} was changed")
            expected_prev = row.row_hash
    return ChainReport(True, count)


def main() -> int:
    """`python -m brain_dock.verify_audit`: check the audit log of the database in use."""
    from brain_dock.core import db

    db_path = db.DB_PATH
    if not db_path.exists():
        print("No database yet. Run: uv run python -m brain_dock.db", file=sys.stderr)
        return 1
    engine = db.get_engine(f"sqlite:///{db_path}")
    try:
        if not db.is_at_head(engine):
            print(
                "The database needs migrating. Run: uv run python -m brain_dock.db", file=sys.stderr
            )
            return 1
        with Session(engine) as session:
            empty = session.exec(select(AuditEvent.id).limit(1)).first() is None
        key_path = key_path_for(db_path)
        if empty and not key_path.exists():
            report = ChainReport(True, 0)
        else:
            report = verify_chain(engine, read_key(key_path))
    except AuditKeyError as e:
        print(f"Can't check the audit log: {e}.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    if not report.ok:
        print(
            f"Audit log BROKEN after {report.entries} entries: {report.problem}.", file=sys.stderr
        )
        return 1
    print(f"Audit log OK: {report.entries} entries, chain intact ({db.display_path(db_path)}).")
    return 0
