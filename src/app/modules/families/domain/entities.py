"""Family identities and relationships, independent of persistence and HTTP."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class RelationshipType(StrEnum):
    PARENT = "parent"
    SPOUSE = "spouse"
    SIBLING = "sibling"
    GUARDIAN = "guardian"


@dataclass(kw_only=True)
class Family:
    id: UUID
    name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class Person:
    id: UUID
    first_name: str
    last_name: str
    birth_date: date | None = None
    gender: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class FamilyMember:
    id: UUID
    family_id: UUID
    person_id: UUID
    role: str = "member"
    joined_at: date


@dataclass(kw_only=True)
class PersonRelationship:
    id: UUID
    person_id: UUID
    related_person_id: UUID
    relationship_type: RelationshipType

    def __post_init__(self) -> None:
        self.relationship_type = RelationshipType(self.relationship_type)
        if self.person_id == self.related_person_id:
            raise ValueError("A person cannot have a relationship with themselves")
        if self.relationship_type in (RelationshipType.SPOUSE, RelationshipType.SIBLING):
            self.person_id, self.related_person_id = sorted(
                (self.person_id, self.related_person_id)
            )


@dataclass(kw_only=True)
class Pet:
    id: UUID
    family_id: UUID
    name: str
    species: str
    breed: str | None = None
    birth_date: date | None = None
    gender: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class PetOwner:
    pet_id: UUID
    person_id: UUID
