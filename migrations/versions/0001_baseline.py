"""Baseline schema: application tables and the pinned Procrastinate queue schema."""

from __future__ import annotations

from alembic import op
from procrastinate.schema import SchemaManager
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

metadata = MetaData()
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("payload", JSONB, nullable=False),
)
messages = Table(
    "messages",
    metadata,
    Column("seq", BigInteger, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSONB, nullable=False),
)
Index("ix_messages_job_seq", messages.c.job_id, messages.c.seq)
attachments = Table(
    "attachments",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSONB, nullable=False),
)
Index("ix_attachments_job", attachments.c.job_id)
events = Table(
    "events",
    metadata,
    Column("seq", BigInteger, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSONB, nullable=False),
)
Index("ix_events_job_seq", events.c.job_id, events.c.seq)
Table(
    "receipts",
    metadata,
    Column("key", String, primary_key=True),
    Column("hash", String, nullable=False),
    Column("result", JSONB, nullable=False),
)
Table(
    "operation_cache",
    metadata,
    Column("key", String, primary_key=True),
    Column("payload", JSONB, nullable=False),
)
knowledge = Table(
    "knowledge",
    metadata,
    Column("id", String, primary_key=True),
    Column("material_id", String),
    Column("property", String, nullable=False),
    Column("aliases", JSONB, nullable=False),
    Column("search", TSVECTOR, nullable=False),
    Column("payload", JSONB, nullable=False),
)
Index("ix_knowledge_search", knowledge.c.search, postgresql_using="gin")
Index("ix_knowledge_material_property", knowledge.c.material_id, knowledge.c.property)
Index("ix_knowledge_aliases", knowledge.c.aliases, postgresql_using="gin")
agent_calls = Table(
    "agent_calls",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("run_id", String, nullable=False),
    Column("agent", String, nullable=False),
    Column("step", Integer, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("request", JSONB, nullable=False),
    Column("response", JSONB),
    Column("tools", JSONB, nullable=False),
    Column("error", Text),
)
Index("ix_agent_calls_job", agent_calls.c.job_id, agent_calls.c.revision)


def upgrade():
    metadata.create_all(op.get_bind())
    op.execute(
        "CREATE INDEX ix_jobs_user_recency ON jobs (user_id, (payload ->> 'updated_at'), id)"
    )
    op.execute(SchemaManager.get_schema())


def downgrade():
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
