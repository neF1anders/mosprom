"""Agent calls answered from the cache are traced too, flagged so token totals skip them."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_calls",
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("agent_calls", "cached")
