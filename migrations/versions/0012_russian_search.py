"""Add Russian stemming without replacing literal keyword search."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector_ru",
            TSVECTOR(),
            sa.Computed("to_tsvector('pg_catalog.russian', text)", persisted=True),
        ),
    )
    op.create_index(
        "idx_chunks_search_ru", "document_chunks", ["search_vector_ru"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("idx_chunks_search_ru", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector_ru")
