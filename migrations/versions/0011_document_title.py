"""Nullable transcript-derived document title; originals and ACL remain unchanged."""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("title", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "title")
