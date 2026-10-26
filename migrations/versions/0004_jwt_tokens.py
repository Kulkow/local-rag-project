"""JWT revocation version; legacy session rows are retained but no longer used."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_check_constraint("ck_users_token_version", "users", "token_version >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_users_token_version", "users", type_="check")
    op.drop_column("users", "token_version")
