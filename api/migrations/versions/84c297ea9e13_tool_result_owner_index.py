"""Index account-scoped tool result retention lookups."""

from alembic import op

revision = "84c297ea9e13"
down_revision = "5d8c2c0d4e51"


def upgrade():
    op.create_index("ix_agent_tool_results_user_expires", "agent_tool_results", ["user_id", "expires_at"])


def downgrade():
    op.drop_index("ix_agent_tool_results_user_expires", table_name="agent_tool_results")
