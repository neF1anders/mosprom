"""Indexes for keyset job history and verified material aliases."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX ix_jobs_recency ON jobs ((payload ->> 'updated_at'), id)")
    op.execute("CREATE INDEX ix_knowledge_aliases ON knowledge USING gin (aliases)")


def downgrade():
    op.drop_index("ix_knowledge_aliases", table_name="knowledge")
    op.drop_index("ix_jobs_recency", table_name="jobs")
