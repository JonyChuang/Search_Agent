"""Persist explicitly granted MCP tool permissions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5d8c2c0d4e51"
down_revision = "f48c07e29bd1"


def upgrade():
    op.add_column("mcp_servers", sa.Column("tool_permissions", postgresql.JSONB(), nullable=True))
    op.create_table(
        "career_context_versions",
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "agent_tool_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade():
    op.drop_table("agent_tool_results")
    op.drop_table("career_context_versions")
    op.drop_column("mcp_servers", "tool_permissions")
