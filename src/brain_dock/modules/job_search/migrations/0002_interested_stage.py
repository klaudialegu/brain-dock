"""interested stage, applied_on optional

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26 17:14:39.548965

Generated with autogenerate, then reviewed: batch mode copies each table (SQLite can't
ALTER these columns in place), keeping every row. Downgrade refuses while saved jobs
exist, because the old schema has no place for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STAGES = (
    "applied",
    "screen",
    "interview",
    "onsite",
    "offer",
    "rejected",
    "ghosted",
    "withdrawn",
)
NEW_STAGES = ("interested", *OLD_STAGES)


def upgrade() -> None:
    with op.batch_alter_table("application", schema=None) as batch_op:
        batch_op.alter_column("applied_on", existing_type=sa.DATE(), nullable=True)
        batch_op.alter_column(
            "current_stage",
            existing_type=sa.VARCHAR(length=9),
            type_=sa.Enum(*NEW_STAGES, name="stage"),
            existing_nullable=False,
        )

    with op.batch_alter_table("stageevent", schema=None) as batch_op:
        batch_op.alter_column(
            "stage",
            existing_type=sa.VARCHAR(length=9),
            type_=sa.Enum(*NEW_STAGES, name="stage"),
            existing_nullable=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    saved = connection.scalar(
        sa.text(
            "SELECT count(*) FROM application WHERE applied_on IS NULL "
            "OR id IN (SELECT application_id FROM stageevent WHERE stage = 'interested')"
        )
    )
    if saved:
        raise RuntimeError(
            f"{saved} saved job(s) use the interested stage; export a backup and remove them "
            "before downgrading"
        )

    with op.batch_alter_table("stageevent", schema=None) as batch_op:
        batch_op.alter_column(
            "stage",
            existing_type=sa.Enum(*NEW_STAGES, name="stage"),
            type_=sa.VARCHAR(length=9),
            existing_nullable=False,
        )

    with op.batch_alter_table("application", schema=None) as batch_op:
        batch_op.alter_column(
            "current_stage",
            existing_type=sa.Enum(*NEW_STAGES, name="stage"),
            type_=sa.VARCHAR(length=9),
            existing_nullable=False,
        )
        batch_op.alter_column("applied_on", existing_type=sa.DATE(), nullable=False)
