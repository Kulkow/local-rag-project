from datetime import date
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.families.application.service import FamilySummary, MemberDetails
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal
from app.modules.shared.domain.errors import ApplicationError


class SqlFamilyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def scope(actor: Principal) -> sa.ColumnElement[bool]:
        if actor.is_admin:
            return sa.true()
        return families.c.id.in_(
            sa.select(family_members.c.family_id).where(
                family_members.c.id == actor.family_member_id
            )
        )

    async def list_families(self, actor: Principal, offset: int, limit: int) -> list[FamilySummary]:
        rows = await self.session.execute(
            sa.select(families.c.id, families.c.name)
            .where(self.scope(actor))
            .order_by(families.c.name, families.c.id)
            .offset(offset)
            .limit(limit)
        )
        return [FamilySummary(*row) for row in rows]

    async def get_family(self, actor: Principal, family_id: UUID) -> FamilySummary:
        row = (
            await self.session.execute(
                sa.select(families.c.id, families.c.name).where(
                    families.c.id == family_id, self.scope(actor)
                )
            )
        ).first()
        if row is None:
            raise ApplicationError("not_found", "Family not found")
        return FamilySummary(*row)

    async def create_family(self, name: str) -> FamilySummary:
        family_id = uuid4()
        await self.session.execute(sa.insert(families).values(id=family_id, name=name))
        return FamilySummary(family_id, name)

    async def rename(self, family_id: UUID, name: str) -> FamilySummary:
        await self.session.execute(
            sa.update(families).where(families.c.id == family_id).values(name=name)
        )
        return FamilySummary(family_id, name)

    async def delete(self, family_id: UUID) -> None:
        await self.session.execute(sa.delete(families).where(families.c.id == family_id))

    @staticmethod
    def member_query() -> sa.Select[tuple[UUID, UUID, str, str, str, date]]:
        return sa.select(
            family_members.c.id,
            family_members.c.person_id,
            persons.c.first_name,
            persons.c.last_name,
            family_members.c.role,
            family_members.c.joined_at,
        ).join(persons, family_members.c.person_id == persons.c.id)

    async def members(self, family_id: UUID, offset: int, limit: int) -> list[MemberDetails]:
        rows = await self.session.execute(
            self.member_query()
            .where(family_members.c.family_id == family_id)
            .order_by(family_members.c.id)
            .offset(offset)
            .limit(limit)
        )
        return [MemberDetails(*row) for row in rows]

    async def one_member(self, family_id: UUID, member_id: UUID) -> MemberDetails:
        row = (
            await self.session.execute(
                self.member_query().where(
                    family_members.c.family_id == family_id, family_members.c.id == member_id
                )
            )
        ).first()
        if row is None:
            raise ApplicationError("not_found", "Member not found")
        return MemberDetails(*row)

    async def add_member(
        self, family_id: UUID, first_name: str, last_name: str, role: str
    ) -> MemberDetails:
        person_id, member_id = uuid4(), uuid4()
        await self.session.execute(
            sa.insert(persons).values(id=person_id, first_name=first_name, last_name=last_name)
        )
        await self.session.execute(
            sa.insert(family_members).values(
                id=member_id, family_id=family_id, person_id=person_id, role=role
            )
        )
        return await self.one_member(family_id, member_id)

    async def change_member(self, family_id: UUID, member_id: UUID, role: str) -> MemberDetails:
        await self.one_member(family_id, member_id)
        await self.session.execute(
            sa.update(family_members)
            .where(family_members.c.family_id == family_id, family_members.c.id == member_id)
            .values(role=role)
        )
        return await self.one_member(family_id, member_id)

    async def remove_member(self, family_id: UUID, member_id: UUID) -> None:
        await self.one_member(family_id, member_id)
        await self.session.execute(
            sa.delete(family_members).where(
                family_members.c.family_id == family_id, family_members.c.id == member_id
            )
        )
