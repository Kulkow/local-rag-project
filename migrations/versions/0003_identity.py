"""Database users, revocable sessions and shared login throttling."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "family_member_id",
            sa.Uuid(),
            sa.ForeignKey("family_members.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('admin', 'manager', 'member')", name="ck_users_role"),
        sa.CheckConstraint(
            "role = 'admin' OR family_member_id IS NOT NULL", name="ck_users_member_link"
        ),
        sa.CheckConstraint(
            "username = lower(username) AND length(username) > 0", name="ck_users_username"
        ),
    )
    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_sessions_user", "user_sessions", ["user_id"])
    op.create_index("idx_sessions_expiry", "user_sessions", ["expires_at"])
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("login_attempts")
    op.drop_table("user_sessions")
    op.drop_table("users")
