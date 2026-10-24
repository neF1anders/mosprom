"""Messages typed while a job works wait here, apart from the chat the agents read."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "queued_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_queued_messages_job_seq", "queued_messages", ["job_id", "seq"])


def downgrade():
    op.drop_table("queued_messages")
