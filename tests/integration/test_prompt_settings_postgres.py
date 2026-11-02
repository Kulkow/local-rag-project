"""Real migrated PostgreSQL persistence and JWT authorization; all writes roll back."""

import os
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import Settings
from app.main import create_app
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository
from app.modules.identity.infrastructure.security import JwtTokens, ScryptPasswords
from app.modules.rag.application.prompt_settings import DEFAULT_SYSTEM_PROMPT
from app.modules.rag.infrastructure.prompt_repository import SqlPromptStore, prompt_settings


async def test_persistent_prompt_settings_with_real_authentication() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to migrated PostgreSQL")
    engine = create_async_engine(url)
    secret = "synthetic-prompt-settings-key-at-least-32-chars"
    try:
        async with engine.connect() as connection, connection.begin() as transaction:
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            # The outer transaction restores any existing setting and all test users.
            await connection.execute(sa.delete(prompt_settings))
            actors = [
                Principal(uuid4(), "prompt-" + uuid4().hex, role, uuid4()) for role in UserRole
            ]
            async with factory() as session, session.begin():
                family_id = uuid4()
                await session.execute(
                    sa.insert(families).values(id=family_id, name="Synthetic settings")
                )
                for actor in actors:
                    person_id = uuid4()
                    await session.execute(
                        sa.insert(persons).values(
                            id=person_id, first_name="Synthetic", last_name="Settings"
                        )
                    )
                    await session.execute(
                        sa.insert(family_members).values(
                            id=actor.family_member_id, person_id=person_id, family_id=family_id
                        )
                    )
                    await SqlIdentityRepository(session).save_user(User(actor, "unused-fixture"))
            app = create_app()
            app.state.settings = Settings(
                database_url=url,
                jwt_secret=secret,
                admin_username="synthetic",
                admin_password="unused-fixture",
            )
            app.state.db_session_factory = factory
            app.state.passwords = ScryptPasswords()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/settings/rag")).status_code == 401
                for actor in actors:
                    headers = {"Authorization": "Bearer " + JwtTokens(secret).issue(actor)}
                    response = await client.get("/settings/rag", headers=headers)
                    if not actor.is_admin:
                        assert response.status_code == 403
                        assert (
                            await client.put(
                                "/settings/rag",
                                headers=headers,
                                json={"system_prompt": "Unapproved", "version": 1},
                            )
                        ).status_code == 403
                        continue
                    assert response.status_code == 200
                    assert response.json()["system_prompt"] == DEFAULT_SYSTEM_PROMPT
                    assert response.json()["version"] == 0
                    for old, text in (
                        (0, "Custom русский prompt {literal}"),
                        (1, DEFAULT_SYSTEM_PROMPT),
                    ):
                        response = await client.put(
                            "/settings/rag",
                            headers=headers,
                            json={"system_prompt": text, "version": old},
                        )
                        assert response.status_code == 200, response.text
                        assert response.json()["version"] == old + 1
                        assert response.json()["updated_at"] is not None
                        assert (await SqlPromptStore(factory).get()).system_prompt == text
                        conflict = await client.put(
                            "/settings/rag",
                            headers=headers,
                            json={"system_prompt": "Stale", "version": old},
                        )
                        assert conflict.status_code == 409
                    assert (await client.get("/settings/rag", headers=headers)).json()[
                        "version"
                    ] == 2
            await transaction.rollback()
    finally:
        await engine.dispose()
