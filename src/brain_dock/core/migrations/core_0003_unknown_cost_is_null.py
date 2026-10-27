"""unknown cost is null

Revision ID: core_0003
Revises: core_0002
Create Date: 2026-10-26 19:20:00

The ledger's cost becomes NULL when it's unknown, so 0 always means free (harness PR 4a).
Generated with autogenerate (the column becomes nullable), then reviewed. The data step is
added by hand: rows written before this migration recorded unknown costs as 0, and those
are the attempts that got no answer (outcomes started, timeout, server_error, failed).
budget_stopped stays 0: nothing was sent, so it was free.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_0003"
down_revision: str | None = "core_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NO_ANSWER = "('started', 'timeout', 'server_error', 'failed')"


def upgrade() -> None:
    with op.batch_alter_table("core_llm_call", schema=None) as batch_op:
        batch_op.alter_column("cost_micro_usd", existing_type=sa.INTEGER(), nullable=True)
    op.execute(
        f"UPDATE core_llm_call SET cost_micro_usd = NULL "
        f"WHERE outcome IN {NO_ANSWER} AND cost_micro_usd = 0"
    )


def downgrade() -> None:
    op.execute("UPDATE core_llm_call SET cost_micro_usd = 0 WHERE cost_micro_usd IS NULL")
    with op.batch_alter_table("core_llm_call", schema=None) as batch_op:
        batch_op.alter_column("cost_micro_usd", existing_type=sa.INTEGER(), nullable=False)
