"""audit log

Revision ID: core_0001
Revises:
Create Date: 2026-10-26 17:44:25.650506

The core's own migration branch (ADR 0008). Generated with autogenerate, then reviewed;
the two append-only triggers are added by hand (autogenerate doesn't see triggers) and
match APPEND_ONLY_SQL in core/agents/audit.py, kept here as a copy so this migration never
changes when that code does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "core_0001"
down_revision: str | None = None
# The core's own branch of the migration history.
branch_labels: str | Sequence[str] | None = ("core",)
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_SQL = (
    "CREATE TRIGGER core_audit_event_no_update BEFORE UPDATE ON core_audit_event "
    "BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END",
    "CREATE TRIGGER core_audit_event_no_delete BEFORE DELETE ON core_audit_event "
    "BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END",
)


def upgrade() -> None:
    op.create_table(
        "core_audit_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("module", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tool", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("outcome", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("input_mac", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prev_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("row_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_audit_event", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_audit_event_prev_hash"), ["prev_hash"], unique=True
        )
        batch_op.create_index(batch_op.f("ix_core_audit_event_run_id"), ["run_id"], unique=False)
    for sql in APPEND_ONLY_SQL:
        op.execute(sql)


def downgrade() -> None:
    op.execute("DROP TRIGGER core_audit_event_no_delete")
    op.execute("DROP TRIGGER core_audit_event_no_update")
    with op.batch_alter_table("core_audit_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_audit_event_run_id"))
        batch_op.drop_index(batch_op.f("ix_core_audit_event_prev_hash"))
    op.drop_table("core_audit_event")
