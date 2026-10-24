"""Results of parameter selection and its check, one per job revision, step and pass."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stage_results",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("job_id", "revision", "stage", "iteration"),
    )


def downgrade():
    op.drop_table("stage_results")
