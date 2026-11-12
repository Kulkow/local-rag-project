"""Optional user description for uploaded files and photos."""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("description", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "description")
