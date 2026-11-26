"""Persisted Agent execution context and tool observations."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text, Uuid, false, func, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.postgres import Base

career_context_versions = Table(
    "career_context_versions", Base.metadata,
    Column("conversation_id", Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
    Column("job_id", Uuid, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("state", JSONB, nullable=False),
    Column("source", String(40), nullable=False),
    Column("field_meta", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

agent_tool_results = Table(
    "agent_tool_results", Base.metadata,
    Column("id", Uuid, primary_key=True),
    Column("conversation_id", Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("job_id", Uuid, nullable=True),
    Column("tool", String(64), nullable=False),
    Column("ciphertext", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Index("ix_agent_tool_results_user_expires", "user_id", "expires_at"),
)

career_queue_samples = Table(
    "career_queue_samples", Base.metadata,
    Column("sampled_at", DateTime(timezone=True), primary_key=True),
    Column("queued", Integer, nullable=False),
    Column("expired_leases", Integer, nullable=False),
    Column("oldest_wait_seconds", Integer, nullable=False),
    Column("alert", Boolean, nullable=False),
    Column("notification_pending", Boolean, nullable=False, server_default=false()),
    Index("ix_career_queue_pending_notification", "sampled_at", postgresql_where=text("notification_pending IS TRUE")),
)
