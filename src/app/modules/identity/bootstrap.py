"""Explicit, idempotent initial admin creation; never silently resets passwords."""

import asyncio
import re
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository
from app.modules.identity.infrastructure.security import ScryptPasswords


async def bootstrap() -> None:
    settings = Settings()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@-]{2,99}", settings.admin_username.strip().lower()):
        raise ValueError(
            "ADMIN_USERNAME must use 3-100 letters, digits, underscores, dots, @ or hyphens"
        )
    if not 12 <= len(settings.admin_password.get_secret_value()) <= 128:
        raise ValueError("ADMIN_PASSWORD must contain 12-128 characters")
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        async with AsyncSession(engine) as session, session.begin():
            repository = SqlIdentityRepository(session)
            if await repository.by_username(settings.admin_username.strip().lower()):
                print("User already exists; no credentials changed")
                return
            principal = Principal(
                uuid4(), settings.admin_username.strip().lower(), UserRole.ADMIN, None
            )
            await repository.save_user(
                User(
                    principal,
                    await ScryptPasswords().hash(settings.admin_password.get_secret_value()),
                )
            )
        print("Initial administrator created")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(bootstrap())
