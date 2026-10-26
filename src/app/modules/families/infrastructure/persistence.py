"""SQLAlchemy mappings for family entities. Import once at the composition root."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import registry

from app.modules.families.domain.entities import (
    Family,
    FamilyMember,
    Person,
    PersonRelationship,
    Pet,
    PetOwner,
    RelationshipType,
)

mapper_registry: registry = registry()
metadata = mapper_registry.metadata


def identity() -> sa.Column[UUID]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            server_onupdate=sa.FetchedValue() if name == "updated_at" else None,
        )
        for name in ("created_at", "updated_at")
    ]


families = sa.Table(
    "families",
    metadata,
    identity(),
    sa.Column("name", sa.String(255), nullable=False),
    *timestamps(),
)
persons = sa.Table(
    "persons",
    metadata,
    identity(),
    sa.Column("first_name", sa.String(100), nullable=False),
    sa.Column("last_name", sa.String(100), nullable=False),
    sa.Column("birth_date", sa.Date()),
    sa.Column("gender", sa.String(20)),
    *timestamps(),
)
family_members = sa.Table(
    "family_members",
    metadata,
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
    sa.Index("idx_family_members_person", "person_id"),
)
person_relationships = sa.Table(
    "person_relationships",
    metadata,
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
    sa.Column(
        "relationship_type",
        sa.Enum(
            RelationshipType,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            create_constraint=False,
            length=50,
        ),
        nullable=False,
    ),
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
    sa.Index("idx_relationships_person", "person_id"),
    sa.Index("idx_relationships_related", "related_person_id"),
)
pets = sa.Table(
    "pets",
    metadata,
    identity(),
    sa.Column(
        "family_id", sa.Uuid(), sa.ForeignKey("families.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("species", sa.String(100), nullable=False),
    sa.Column("breed", sa.String(100)),
    sa.Column("birth_date", sa.Date()),
    sa.Column("gender", sa.String(20)),
    *timestamps(),
    sa.Index("idx_pets_family", "family_id"),
)
pet_owners = sa.Table(
    "pet_owners",
    metadata,
    sa.Column("pet_id", sa.Uuid(), sa.ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True),
    sa.Column(
        "person_id", sa.Uuid(), sa.ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Index("idx_pet_owners_person", "person_id"),
)

for entity, table in (
    (Family, families),
    (Person, persons),
    (FamilyMember, family_members),
    (PersonRelationship, person_relationships),
    (Pet, pets),
    (PetOwner, pet_owners),
):
    mapper_registry.map_imperatively(entity, table)
