"""Persist installed skill package releases."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f48c07e29bd1"
down_revision = "f0bcda341a75"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("package_id", sa.String(64), nullable=True))
    op.add_column("skills", sa.Column("package_data", JSONB, nullable=True))
    op.create_unique_constraint("uq_skill_user_package", "skills", ["user_id", "package_id"])


def downgrade() -> None:
    op.drop_constraint("uq_skill_user_package", "skills", type_="unique")
    op.drop_column("skills", "package_data")
    op.drop_column("skills", "package_id")

