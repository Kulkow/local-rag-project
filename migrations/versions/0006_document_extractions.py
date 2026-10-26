"""Bounded text extraction lifecycle, separate from upload and RAG indexing."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("character_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(50)),
        sa.Column("artifact_key", sa.String(255)),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'extracted', 'failed')", name="ck_extraction_status"
        ),
        sa.CheckConstraint(
            "page_count >= 0 AND page_count <= 200 AND character_count >= 0",
            name="ck_extraction_counts",
        ),
    )


def downgrade() -> None:
    op.drop_table("document_extractions")
