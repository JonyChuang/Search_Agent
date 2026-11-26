"""Persisted Agent execution context and tool observations."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.postgres import Base

career_context_versions = Table(
    "career_context_versions", Base.metadata,
    Column("conversation_id", Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
    Column("job_id", Uuid, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("state", JSONB, nullable=False),
    Column("source", String(40), nullable=False),
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
)
