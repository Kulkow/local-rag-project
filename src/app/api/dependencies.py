from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.families.application.service import FamilyService
from app.modules.families.infrastructure.repository import SqlFamilyRepository
from app.modules.identity.application.service import IdentityService
from app.modules.identity.domain.entities import Principal
from app.modules.identity.infrastructure.repository import SqlIdentityRepository
from app.modules.identity.infrastructure.security import ScryptPasswords, JwtTokens
from app.modules.shared.domain.errors import ApplicationError

bearer = HTTPBearer(auto_error=False)


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    async with factory() as session:
        async with session.begin():
            yield session


def identity_service(
    request: Request, session: Annotated[AsyncSession, Depends(db_session)]
) -> IdentityService:
    passwords: ScryptPasswords = request.app.state.passwords
    return IdentityService(
        SqlIdentityRepository(session),
        passwords,
        JwtTokens(request.app.state.settings.jwt_secret.get_secret_value()),
    )


def family_service(session: Annotated[AsyncSession, Depends(db_session)]) -> FamilyService:
    return FamilyService(SqlFamilyRepository(session))


async def current_user(
    service: Annotated[IdentityService, Depends(identity_service)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise ApplicationError("unauthorized", "Authentication required")
    return await service.authenticate(credentials.credentials)
