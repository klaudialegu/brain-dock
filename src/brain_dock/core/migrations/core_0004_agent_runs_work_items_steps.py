"""agent runs work items steps

Revision ID: core_0004
Revises: core_0003
Create Date: 2026-10-26 19:16:03.958090

Durable runs (harness PR 4a): runs, work items and flight-recorder steps. Generated with
autogenerate, then reviewed: it only adds tables, so no existing row is touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "core_0004"
down_revision: str | None = "core_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "core_agent_run",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("module", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("started_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("finished_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("budget_limit_micro_usd", sa.Integer(), nullable=False),
        sa.Column("spent_micro_usd", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_agent_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_core_agent_run_module"), ["module"], unique=False)

    op.create_table(
        "core_run_step",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("decision", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("prompt_version", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("cost_micro_usd", sa.Integer(), nullable=True),
        sa.Column("detail", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_run_step", schema=None) as batch_op:
        batch_op.create_index("ix_core_run_step_run_seq", ["run_id", "seq"], unique=True)

    op.create_table(
        "core_work_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_work_item", schema=None) as batch_op:
        batch_op.create_index("ix_core_work_item_module_key", ["module", "key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("core_work_item", schema=None) as batch_op:
        batch_op.drop_index("ix_core_work_item_module_key")

    op.drop_table("core_work_item")
    with op.batch_alter_table("core_run_step", schema=None) as batch_op:
        batch_op.drop_index("ix_core_run_step_run_seq")

    op.drop_table("core_run_step")
    with op.batch_alter_table("core_agent_run", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_agent_run_module"))

    op.drop_table("core_agent_run")
