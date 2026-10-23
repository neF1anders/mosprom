"""Persistence schema. JSON payloads are versioned domain values, not ORM entities."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

metadata = MetaData()
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
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
receipts = Table(
    "receipts",
    metadata,
    Column("key", String, primary_key=True),
    Column("hash", String, nullable=False),
    Column("result", JSONB, nullable=False),
)
cache = Table(
    "operation_cache",
    metadata,
    Column("key", String, primary_key=True),
    Column("payload", JSONB, nullable=False),
)
cards = Table(
    "cards",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("payload", JSONB, nullable=False),
)
queue = Table(
    "work_queue",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("owner", String, nullable=False, server_default=""),
    Column("lease_until", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False, server_default="0"),
    UniqueConstraint("job_id", "revision", name="uq_work_revision"),
)
Index("ix_queue_status_lease", queue.c.status, queue.c.lease_until)
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

Index("ix_jobs_recency", jobs.c.payload["updated_at"].astext, jobs.c.id)
Index("ix_knowledge_aliases", knowledge.c.aliases, postgresql_using="gin")
