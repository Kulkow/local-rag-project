"""Family, people, relationships and pets."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def identity() -> sa.Column[sa.Uuid]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def timestamps() -> Sequence[sa.Column[sa.DateTime]]:
    return [
        sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "families", identity(), sa.Column("name", sa.String(255), nullable=False), *timestamps()
    )
    op.create_table(
        "persons",
        identity(),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("birth_date", sa.Date()),
        sa.Column("gender", sa.String(20)),
        *timestamps(),
    )
    op.create_table(
        "family_members",
        identity(),
        sa.Column(
            "family_id", sa.Uuid(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "person_id", sa.Uuid(), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(50), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.UniqueConstraint("family_id", "person_id", name="uq_family_members_family_person"),
    )
    op.create_table(
        "person_relationships",
        identity(),
        sa.Column(
            "person_id", sa.Uuid(), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "related_person_id",
            sa.Uuid(),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.CheckConstraint("person_id <> related_person_id", name="ck_relationship_not_self"),
        sa.CheckConstraint(
            "relationship_type IN ('parent', 'spouse', 'sibling', 'guardian')",
            name="ck_relationship_type",
        ),
        sa.CheckConstraint(
            "relationship_type NOT IN ('spouse', 'sibling') OR person_id < related_person_id",
            name="ck_relationship_symmetric_order",
        ),
        sa.UniqueConstraint(
            "person_id", "related_person_id", "relationship_type", name="uq_relationship_pair_type"
        ),
    )
    op.create_table(
        "pets",
        identity(),
        sa.Column(
            "family_id",
            sa.Uuid(),
            sa.ForeignKey("families.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("species", sa.String(100), nullable=False),
        sa.Column("breed", sa.String(100)),
        sa.Column("birth_date", sa.Date()),
        sa.Column("gender", sa.String(20)),
        *timestamps(),
    )
    op.create_table(
        "pet_owners",
        sa.Column(
            "pet_id", sa.Uuid(), sa.ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "person_id",
            sa.Uuid(),
            sa.ForeignKey("persons.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    for table, name, column in (
        ("family_members", "idx_family_members_person", "person_id"),
        ("pets", "idx_pets_family", "family_id"),
        ("pet_owners", "idx_pet_owners_person", "person_id"),
        ("person_relationships", "idx_relationships_person", "person_id"),
        ("person_relationships", "idx_relationships_related", "related_person_id"),
    ):
        op.create_index(name, table, [column])
    op.execute("""
        CREATE FUNCTION family_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    for table in ("families", "persons", "pets"):
        op.execute(
            f"CREATE TRIGGER set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION family_set_updated_at()"
        )


def downgrade() -> None:
    for table in (
        "pet_owners",
        "person_relationships",
        "family_members",
        "pets",
        "persons",
        "families",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION family_set_updated_at()")
