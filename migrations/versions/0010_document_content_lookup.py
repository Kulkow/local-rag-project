"""Index owner/content reservations without deleting pre-existing duplicates."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_documents_owner_checksum", "documents", ["owner_id", "checksum"])


def downgrade() -> None:
    op.drop_index("idx_documents_owner_checksum", table_name="documents")
