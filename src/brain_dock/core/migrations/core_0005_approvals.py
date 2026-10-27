"""approvals

Revision ID: core_0005
Revises: core_0004
Create Date: 2026-10-26 19:36:46.193700

Approvals (harness PR 4b). Generated with autogenerate, then reviewed: it only adds a
table, so no existing row is touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "core_0005"
down_revision: str | None = "core_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "core_approval",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("module", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("tool", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("input_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("input_mac", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("decided_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("decided_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_approval", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_core_approval_run_id"), ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("core_approval", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_approval_run_id"))

    op.drop_table("core_approval")
