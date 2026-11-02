"""Persist the administrator-configured RAG generation prompt."""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_prompt_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="rag_prompt_singleton"),
        sa.CheckConstraint("version > 0", name="rag_prompt_version_positive"),
        sa.CheckConstraint(
            "length(btrim(system_prompt)) BETWEEN 1 AND 8000", name="rag_prompt_length"
        ),
    )


def downgrade() -> None:
    op.drop_table("rag_prompt_settings")
