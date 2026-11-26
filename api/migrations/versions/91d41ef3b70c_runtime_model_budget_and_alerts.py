"""Store model-specific context sizes and pending queue alert deliveries."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "91d41ef3b70c"
down_revision = "e43bb0cd41a2"


def upgrade() -> None:
    op.add_column("model_configs", sa.Column("context_window_tokens", sa.Integer(), nullable=True))
    op.add_column("career_context_versions", sa.Column("field_meta", JSONB(), nullable=True))
    op.add_column("career_queue_samples", sa.Column("notification_pending", sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.create_index("ix_career_queue_pending_notification", "career_queue_samples", ["sampled_at"],
                    postgresql_where=sa.text("notification_pending IS TRUE"))


def downgrade() -> None:
    op.drop_index("ix_career_queue_pending_notification", table_name="career_queue_samples")
    op.drop_column("career_queue_samples", "notification_pending")
    op.drop_column("career_context_versions", "field_meta")
    op.drop_column("model_configs", "context_window_tokens")
