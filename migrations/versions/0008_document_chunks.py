"""Chunk catalog and reproducible embedding index configuration."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_indexes",
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=False),
        sa.Column("extraction_generation", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("collection_name", sa.String(100), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_digest", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(50), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(50)),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('indexing', 'indexed', 'failed')", name="ck_document_index_status"
        ),
        sa.CheckConstraint(
            "dimensions > 0 AND chunk_count >= 0 AND chunk_size > 0 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_document_index_configuration",
        ),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("index_generation", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector", TSVECTOR(), sa.Computed("to_tsvector('simple', text)", persisted=True)
        ),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_ordinal"),
        sa.CheckConstraint(
            "ordinal >= 0 AND page_number >= 1 AND start_offset >= 0 AND end_offset > start_offset",
            name="ck_document_chunk_offsets",
        ),
    )
    op.create_index(
        "idx_chunks_document_generation", "document_chunks", ["document_id", "index_generation"]
    )
    op.create_index(
        "idx_chunks_search", "document_chunks", ["search_vector"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("document_indexes")
