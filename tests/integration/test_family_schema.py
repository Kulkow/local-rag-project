"""Exercise database constraints with synthetic records and roll everything back."""

import os
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.families.infrastructure.persistence import (
    families as Family,
    family_members as FamilyMember,
    persons as Person,
    person_relationships as PersonRelationship,
    pets as Pet,
    pet_owners as PetOwner,
)


async def test_family_schema_constraints() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:

                async def insert_id(table: sa.Table, **values: object) -> UUID:
                    return (
                        await connection.execute(
                            sa.insert(table).values(**values).returning(table.c.id)
                        )
                    ).scalar_one()

                async def rejected(statement: sa.Executable) -> None:
                    async with connection.begin_nested() as savepoint:
                        with pytest.raises(IntegrityError):
                            await connection.execute(statement)
                        await savepoint.rollback()

                family = await insert_id(Family, name="Synthetic family")
                other_family = await insert_id(Family, name="Other family")
                person = await insert_id(Person, first_name="Alex", last_name="Example")
                relative = await insert_id(Person, first_name="Sam", last_name="Example")
                pet = await insert_id(Pet, family_id=family, name="Test pet", species="cat")
                membership = sa.insert(FamilyMember).values(family_id=family, person_id=person)
                await connection.execute(membership)
                await connection.execute(
                    sa.insert(FamilyMember).values(family_id=other_family, person_id=person)
                )
                await rejected(membership)
                await rejected(
                    sa.insert(FamilyMember).values(family_id=UUID(int=0), person_id=person)
                )
                owner = sa.insert(PetOwner).values(pet_id=pet, person_id=person)
                await connection.execute(owner)
                await connection.execute(sa.insert(PetOwner).values(pet_id=pet, person_id=relative))
                await rejected(owner)
                await rejected(sa.insert(PetOwner).values(pet_id=UUID(int=0), person_id=person))
                relation = sa.insert(PersonRelationship)
                await rejected(
                    relation.values(
                        person_id=person, related_person_id=person, relationship_type="parent"
                    )
                )
                first, second = sorted([person, relative])
                symmetric = relation.values(
                    person_id=first, related_person_id=second, relationship_type="spouse"
                )
                await connection.execute(symmetric)
                await rejected(symmetric)
                await rejected(
                    relation.values(
                        person_id=second, related_person_id=first, relationship_type="spouse"
                    )
                )
                await connection.execute(
                    relation.values(
                        person_id=person, related_person_id=relative, relationship_type="parent"
                    )
                )
                await rejected(
                    relation.values(
                        person_id=person, related_person_id=relative, relationship_type="unknown"
                    )
                )
                await rejected(sa.delete(Family).where(Family.c.id == family))
                before = (
                    await connection.execute(
                        sa.select(Family.c.updated_at).where(Family.c.id == family)
                    )
                ).scalar_one()
                await connection.execute(
                    sa.update(Family).where(Family.c.id == family).values(name="Renamed")
                )
                after = (
                    await connection.execute(
                        sa.select(Family.c.updated_at).where(Family.c.id == family)
                    )
                ).scalar_one()
                assert after > before
                await connection.execute(sa.delete(Person).where(Person.c.id == person))
                assert (
                    await connection.execute(
                        sa.select(sa.func.count())
                        .select_from(FamilyMember)
                        .where(FamilyMember.c.person_id == person)
                    )
                ).scalar_one() == 0
                assert (
                    await connection.execute(
                        sa.select(sa.func.count())
                        .select_from(PersonRelationship)
                        .where(
                            sa.or_(
                                PersonRelationship.c.person_id == person,
                                PersonRelationship.c.related_person_id == person,
                            )
                        )
                    )
                ).scalar_one() == 0
                await connection.execute(sa.delete(Pet).where(Pet.c.id == pet))
                assert (
                    await connection.execute(
                        sa.select(sa.func.count())
                        .select_from(PetOwner)
                        .where(PetOwner.c.pet_id == pet)
                    )
                ).scalar_one() == 0
                await connection.execute(sa.delete(Family).where(Family.c.id == family))
                await connection.execute(
                    sa.insert(FamilyMember).values(family_id=other_family, person_id=relative)
                )
                await connection.execute(sa.delete(Family).where(Family.c.id == other_family))
                assert (
                    await connection.execute(sa.select(Person.c.id).where(Person.c.id == relative))
                ).scalar_one() == relative
                assert (
                    await connection.execute(
                        sa.select(sa.func.count())
                        .select_from(FamilyMember)
                        .where(FamilyMember.c.family_id == other_family)
                    )
                ).scalar_one() == 0
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def test_domain_entities_round_trip() -> None:
    from datetime import date
    from uuid import uuid4

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.families.domain import entities

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    family = entities.Family(id=uuid4(), name="Synthetic ORM family")
                    person = entities.Person(id=uuid4(), first_name="Alex", last_name="Example")
                    relative = entities.Person(
                        id=UUID(int=1), first_name="Sam", last_name="Example"
                    )
                    # IDs must not collide with actual records; order deliberately reversed.
                    person.id, relative.id = sorted([uuid4(), uuid4()], reverse=True)
                    session.add_all([family, person, relative])
                    await session.flush()
                    pet = entities.Pet(id=uuid4(), family_id=family.id, name="Test", species="cat")
                    member = entities.FamilyMember(
                        id=uuid4(),
                        family_id=family.id,
                        person_id=person.id,
                        joined_at=date(2026, 1, 1),
                    )
                    relation = entities.PersonRelationship(
                        id=uuid4(),
                        person_id=person.id,
                        related_person_id=relative.id,
                        relationship_type=entities.RelationshipType.SPOUSE,
                    )
                    session.add_all([pet, member, relation])
                    await session.flush()
                    session.add(entities.PetOwner(pet_id=pet.id, person_id=person.id))
                    await session.flush()
                    assert family.created_at is not None
                    assert family.updated_at is not None
                    family_id, pet_id, person_id, relation_id = (
                        family.id,
                        pet.id,
                        person.id,
                        relation.id,
                    )
                    session.expunge_all()
                    loaded = await session.get(entities.Family, family_id)
                    assert loaded is not None and loaded.name == "Synthetic ORM family"
                    assert await session.get(entities.Pet, pet_id) is not None
                    assert await session.get(entities.PetOwner, (pet_id, person_id)) is not None
                    loaded_relation = await session.get(entities.PersonRelationship, relation_id)
                    assert loaded_relation is not None
                    assert loaded_relation.person_id < loaded_relation.related_person_id
                    assert loaded_relation.relationship_type is entities.RelationshipType.SPOUSE
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
