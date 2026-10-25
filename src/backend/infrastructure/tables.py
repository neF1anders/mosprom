from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    false,
)

metadata = MetaData()
jobs = Table(
    "jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index("ix_jobs_user_recency", jobs.c.user_id, jobs.c.payload["updated_at"].as_string(), jobs.c.id)
messages = Table(
    "messages",
    metadata,
    Column("seq", Integer, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index("ix_messages_job_seq", messages.c.job_id, messages.c.seq)
attachments = Table(
    "attachments",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index("ix_attachments_job", attachments.c.job_id)
events = Table(
    "events",
    metadata,
    Column("seq", Integer, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index("ix_events_job_seq", events.c.job_id, events.c.seq)
receipts = Table(
    "receipts",
    metadata,
    Column("key", String, primary_key=True),
    Column("hash", String, nullable=False),
    Column("result", JSON, nullable=False),
)
cache = Table(
    "operation_cache",
    metadata,
    Column("key", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)
knowledge = Table(
    "knowledge",
    metadata,
    Column("id", String, primary_key=True),
    Column("material_id", String),
    Column("property", String, nullable=False),
    Column("aliases", JSON, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index("ix_knowledge_material_property", knowledge.c.material_id, knowledge.c.property)
agent_calls = Table(
    "agent_calls",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("run_id", String, nullable=False),
    Column("agent", String, nullable=False),
    Column("step", Integer, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("request", JSON, nullable=False),
    Column("response", JSON),
    Column("tools", JSON, nullable=False),
    Column("error", Text),
    Column("cached", Boolean, nullable=False, server_default=false()),
)
Index("ix_agent_calls_job", agent_calls.c.job_id, agent_calls.c.revision)
stage_results = Table(
    "stage_results",
    metadata,
    Column("job_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("stage", String, nullable=False),
    Column("iteration", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    PrimaryKeyConstraint("job_id", "revision", "stage", "iteration"),
)
queued_messages = Table(
    "queued_messages",
    metadata,
    # порядок по rowid
    Column("seq", Integer, primary_key=True),
    Column("id", String, nullable=False, unique=True),
    Column("job_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index("ix_queued_messages_job_seq", queued_messages.c.job_id, queued_messages.c.seq)
# очередь работы этапов
task_queue = Table(
    "task_queue",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("task", String, nullable=False),
    Column("lock", String, nullable=False),
    Column("job_id", String, nullable=False),
    Column("args", JSON, nullable=False),
    Column("status", String, nullable=False, server_default="todo"),
)
Index("ix_task_queue_status", task_queue.c.status, task_queue.c.id)
