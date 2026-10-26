"""Family authorization adapter shared by API and background processing."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.families.application.service import FamilyService, FamilySummary
from app.modules.families.infrastructure.repository import SqlFamilyRepository
from app.modules.identity.application.contracts import Principal


class ScopedFamilyAccess:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def authorize(
        self, actor: Principal, family_id: UUID, write: bool = False
    ) -> FamilySummary:
        async with self.factory() as session:
            return await FamilyService(SqlFamilyRepository(session)).authorize(
                actor, family_id, write
            )
