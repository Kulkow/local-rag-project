from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from app.modules.identity.application.contracts import Principal, UserRole
from app.modules.shared.domain.errors import ApplicationError


@dataclass(frozen=True)
class FamilySummary:
    id: UUID
    name: str


@dataclass(frozen=True)
class MemberDetails:
    id: UUID
    person_id: UUID
    first_name: str
    last_name: str
    role: str
    joined_at: date


class FamilyRepository(Protocol):
    async def list_families(
        self, actor: Principal, offset: int, limit: int
    ) -> list[FamilySummary]: ...
    async def get_family(self, actor: Principal, family_id: UUID) -> FamilySummary: ...
    async def create_family(self, name: str) -> FamilySummary: ...
    async def rename(self, family_id: UUID, name: str) -> FamilySummary: ...
    async def delete(self, family_id: UUID) -> None: ...
    async def members(self, family_id: UUID, offset: int, limit: int) -> list[MemberDetails]: ...
    async def add_member(
        self, family_id: UUID, first_name: str, last_name: str, role: str
    ) -> MemberDetails: ...
    async def change_member(self, family_id: UUID, member_id: UUID, role: str) -> MemberDetails: ...
    async def remove_member(self, family_id: UUID, member_id: UUID) -> None: ...


class FamilyService:
    def __init__(self, repository: FamilyRepository) -> None:
        self.repository = repository

    async def authorize(
        self, actor: Principal, family_id: UUID, write: bool = False
    ) -> FamilySummary:
        family = await self.repository.get_family(actor, family_id)
        if write and actor.role not in (UserRole.ADMIN, UserRole.MANAGER):
            raise ApplicationError("forbidden", "Family management permission required")
        return family

    async def list_families(self, actor: Principal, offset: int, limit: int) -> list[FamilySummary]:
        return await self.repository.list_families(actor, offset, limit)

    async def create(self, actor: Principal, name: str) -> FamilySummary:
        if not actor.is_admin:
            raise ApplicationError("forbidden", "Only administrators can create families")
        return await self.repository.create_family(name)

    async def rename(self, actor: Principal, family_id: UUID, name: str) -> FamilySummary:
        await self.authorize(actor, family_id, write=True)
        return await self.repository.rename(family_id, name)

    async def delete(self, actor: Principal, family_id: UUID) -> None:
        await self.authorize(actor, family_id, write=True)
        if not actor.is_admin:
            raise ApplicationError("forbidden", "Only administrators can delete families")
        await self.repository.delete(family_id)

    async def members(
        self, actor: Principal, family_id: UUID, offset: int, limit: int
    ) -> list[MemberDetails]:
        await self.authorize(actor, family_id)
        return await self.repository.members(family_id, offset, limit)

    async def add_member(
        self, actor: Principal, family_id: UUID, first_name: str, last_name: str, role: str
    ) -> MemberDetails:
        await self.authorize(actor, family_id, write=True)
        return await self.repository.add_member(family_id, first_name, last_name, role)

    async def change_member(
        self, actor: Principal, family_id: UUID, member_id: UUID, role: str
    ) -> MemberDetails:
        await self.authorize(actor, family_id, write=True)
        return await self.repository.change_member(family_id, member_id, role)

    async def remove_member(self, actor: Principal, family_id: UUID, member_id: UUID) -> None:
        await self.authorize(actor, family_id, write=True)
        await self.repository.remove_member(family_id, member_id)
