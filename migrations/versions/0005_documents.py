"""Document originals and durable upload lifecycle; no index or retrieval yet."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "family_id",
            sa.Uuid(),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False, unique=True),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("visibility IN ('private', 'family')", name="ck_documents_visibility"),
        sa.CheckConstraint(
            "status IN ('uploading', 'uploaded', 'upload_failed')", name="ck_documents_status"
        ),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_documents_size"),
    )
    op.create_index("idx_documents_family_created", "documents", ["family_id", "created_at"])
    op.create_index("idx_documents_owner", "documents", ["owner_id"])


def downgrade() -> None:
    op.drop_table("documents")
