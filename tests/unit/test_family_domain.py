from uuid import UUID, uuid4

import pytest

from app.modules.families.domain.entities import PersonRelationship, RelationshipType


@pytest.mark.parametrize("kind", [RelationshipType.SPOUSE, RelationshipType.SIBLING])
def test_symmetric_relationships_are_canonical(kind: RelationshipType) -> None:
    first, second = UUID(int=1), UUID(int=2)
    forward = PersonRelationship(
        id=uuid4(), person_id=first, related_person_id=second, relationship_type=kind
    )
    reverse = PersonRelationship(
        id=uuid4(), person_id=second, related_person_id=first, relationship_type=kind
    )
    assert (forward.person_id, forward.related_person_id) == (
        reverse.person_id,
        reverse.related_person_id,
    )


@pytest.mark.parametrize("kind", [RelationshipType.PARENT, RelationshipType.GUARDIAN])
def test_directed_relationships_keep_direction(kind: RelationshipType) -> None:
    parent, child = UUID(int=2), UUID(int=1)
    relationship = PersonRelationship(
        id=uuid4(), person_id=parent, related_person_id=child, relationship_type=kind
    )
    assert (relationship.person_id, relationship.related_person_id) == (parent, child)


@pytest.mark.parametrize("kind", list(RelationshipType))
def test_self_relationship_is_rejected(kind: RelationshipType) -> None:
    person = uuid4()
    with pytest.raises(ValueError):
        PersonRelationship(
            id=uuid4(), person_id=person, related_person_id=person, relationship_type=kind
        )
