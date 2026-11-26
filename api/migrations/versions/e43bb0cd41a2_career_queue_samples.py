"""Persist bounded queue monitoring samples."""

import sqlalchemy as sa
from alembic import op

revision = "e43bb0cd41a2"
down_revision = "84c297ea9e13"


def upgrade():
    op.create_table(
        "career_queue_samples",
        sa.Column("sampled_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("queued", sa.Integer(), nullable=False),
        sa.Column("expired_leases", sa.Integer(), nullable=False),
        sa.Column("oldest_wait_seconds", sa.Integer(), nullable=False),
        sa.Column("alert", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("career_queue_samples")
