"""Associate company research reports with saved career jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f0bcda341a75"
down_revision = "6727223d45f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_reports", sa.Column("job_id", UUID(as_uuid=True), nullable=True))
    op.add_column("research_reports", sa.Column("saved_document_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_research_reports_saved_document", "research_reports", "documents",
        ["saved_document_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_research_reports_user_job_created",
        "research_reports",
        ["user_id", "job_id", "created_at"],
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_research_reports_user_job_created", table_name="research_reports")
    op.drop_constraint("fk_research_reports_saved_document", "research_reports", type_="foreignkey")
    op.drop_column("research_reports", "saved_document_id")
    op.drop_column("research_reports", "job_id")
