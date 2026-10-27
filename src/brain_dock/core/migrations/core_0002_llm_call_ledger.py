"""llm call ledger

Revision ID: core_0002
Revises: core_0001
Create Date: 2026-10-26 18:51:44.103978

The model-call ledger (ADR 0008, PR 3c). Generated with autogenerate, then reviewed: it
only adds a table, so no existing row is touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "core_0002"
down_revision: str | None = "core_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "core_llm_call",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("module", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("route", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prompt_version", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("outcome", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=False),
        sa.Column("prices_verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_llm_call", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_core_llm_call_run_id"), ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("core_llm_call", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_llm_call_run_id"))

    op.drop_table("core_llm_call")
