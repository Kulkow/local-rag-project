"""Real PostgreSQL API workflow with synthetic users and explicit cleanup."""

import os
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.settings import Settings
from app.main import create_app
from app.modules.families.infrastructure.persistence import families, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository, users
from app.modules.identity.infrastructure.security import ScryptPasswords


async def test_authorized_family_and_user_management() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL database")
    prefix = f"test-{uuid4().hex}"
    password = "synthetic-password-123"
    family_ids: list[str] = []
    person_ids: list[str] = []
    engine = create_async_engine(url)
    admin = Principal(uuid4(), prefix, UserRole.ADMIN, None)
    try:
        async with AsyncSession(engine) as session, session.begin():
            await SqlIdentityRepository(session).save_user(
                User(admin, await ScryptPasswords().hash(password))
            )
        app = create_app(
            Settings(
                jwt_secret="test-signing-key-for-jwt-only-123456",
                database_url=url,
                admin_username="test-admin",
                admin_password=password,
            )
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=(prefix, 1)), base_url="http://test"
            ) as client:

                async def login(username: str) -> dict[str, str]:
                    response = await client.post(
                        "/auth/login", json={"username": username, "password": password}
                    )
                    assert response.status_code == 200, response.text
                    assert response.headers["cache-control"] == "no-store"
                    return {"Authorization": "Bearer " + response.json()["access_token"]}

                async def create_family(headers: dict[str, str], name: str) -> str:
                    response = await client.post("/families", headers=headers, json={"name": name})
                    assert response.status_code == 201, response.text
                    family_ids.append(response.json()["id"])
                    return response.json()["id"]

                async def add_member(headers: dict[str, str], family_id: str, name: str) -> str:
                    response = await client.post(
                        f"/families/{family_id}/members",
                        headers=headers,
                        json={"first_name": name, "last_name": prefix},
                    )
                    assert response.status_code == 201, response.text
                    person_ids.append(response.json()["person_id"])
                    return response.json()["id"]

                assert (await client.get("/families")).status_code == 401
                bad = await client.post(
                    "/auth/login", json={"username": prefix, "password": "wrong"}
                )
                assert bad.status_code == 401
                headers = await login(prefix)
                async with AsyncSession(engine) as verification:
                    count = (
                        await verification.execute(
                            sa.text("SELECT count(*) FROM user_sessions WHERE user_id = :id"),
                            {"id": admin.id},
                        )
                    ).scalar_one()
                    assert count == 0  # JWT login does not persist authentication sessions.
                assert (await client.get("/ready", headers=headers)).status_code in (200, 503)
                assert (await client.get("/auth/me", headers=headers)).json()["id"] == str(admin.id)
                family1 = await create_family(headers, "Synthetic family A")
                family2 = await create_family(headers, "Synthetic family B")
                member1 = await add_member(headers, family1, "Alex")
                await add_member(headers, family2, "Sam")
                manager_input = {
                    "username": prefix + "-manager",
                    "password": password,
                    "role": "manager",
                    "family_member_id": member1,
                }
                response = await client.post("/users", headers=headers, json=manager_input)
                assert response.status_code == 201, response.text
                manager_id = response.json()["id"]
                assert "password" not in response.text
                assert (
                    await client.post("/users", headers=headers, json=manager_input)
                ).status_code == 409
                assert (
                    await client.post(
                        "/users",
                        headers=headers,
                        json={**manager_input, "username": prefix + "-duplicate-link"},
                    )
                ).status_code == 409
                assert (
                    await client.post(
                        "/users", headers=headers, json={**manager_input, "family_member_id": None}
                    )
                ).status_code == 422
                invalid = await client.post(
                    "/users",
                    headers=headers,
                    json={**manager_input, "password": "xY!7"},
                )
                assert invalid.status_code == 422
                assert "xY!7" not in invalid.text
                manager = await login(prefix + "-manager")
                assert (await client.get("/ready", headers=manager)).status_code == 403
                visible = (await client.get("/families", headers=manager)).json()
                assert [family["id"] for family in visible] == [family1]
                assert (
                    await client.get(f"/families/{family2}/members", headers=manager)
                ).status_code == 404
                assert (
                    await client.put(
                        f"/families/{family2}", headers=manager, json={"name": "Forbidden"}
                    )
                ).status_code == 404
                assert (
                    await client.post("/families", headers=manager, json={"name": "Forbidden"})
                ).status_code == 403
                assert (await client.get("/users", headers=manager)).status_code == 403
                assert (
                    await client.post("/users", headers=manager, json=manager_input)
                ).status_code == 403
                assert (
                    await client.put(
                        f"/families/{family1}", headers=manager, json={"name": "Renamed"}
                    )
                ).status_code == 200
                member3 = await add_member(manager, family1, "Taylor")
                assert (
                    await client.patch(
                        f"/families/{family1}/members/{member3}",
                        headers=manager,
                        json={"role": "parent"},
                    )
                ).status_code == 200
                created = await client.post(
                    "/users",
                    headers=headers,
                    json={
                        "username": prefix + "-member",
                        "password": password,
                        "role": "member",
                        "family_member_id": member3,
                    },
                )
                assert created.status_code == 201
                member = await login(prefix + "-member")
                assert (
                    await client.get(f"/families/{family1}/members", headers=member)
                ).status_code == 200
                assert (
                    await client.put(
                        f"/families/{family1}", headers=member, json={"name": "Forbidden"}
                    )
                ).status_code == 403
                assert (
                    await client.delete(f"/families/{family1}/members/{member3}", headers=manager)
                ).status_code == 409
                assert (
                    await client.delete(f"/families/{family1}", headers=headers)
                ).status_code == 409
                empty = await create_family(headers, "Synthetic empty family")
                assert (
                    await client.delete(f"/families/{empty}", headers=headers)
                ).status_code == 204
                updated = await client.put(
                    f"/users/{manager_id}",
                    headers=headers,
                    json={"role": "manager", "is_active": False, "family_member_id": member1},
                )
                assert updated.status_code == 200
                assert (await client.get("/families", headers=manager)).status_code == 401
                assert (
                    await client.post(
                        "/auth/login", json={"username": prefix + "-manager", "password": password}
                    )
                ).status_code == 401
                assert (await client.post("/auth/logout", headers=member)).status_code == 204
                assert (await client.get("/auth/me", headers=member)).status_code == 401
                reset = await client.put(
                    f"/users/{manager_id}",
                    headers=headers,
                    json={
                        "role": "manager",
                        "is_active": True,
                        "family_member_id": member1,
                        "password": "changed-synthetic-pass-456",
                    },
                )
                assert reset.status_code == 200
                assert (
                    await client.post(
                        "/auth/login", json={"username": prefix + "-manager", "password": password}
                    )
                ).status_code == 401
                fresh = await client.post(
                    "/auth/login",
                    json={
                        "username": prefix + "-manager",
                        "password": "changed-synthetic-pass-456",
                    },
                )
                assert fresh.status_code == 200
                fresh_headers = {"Authorization": "Bearer " + fresh.json()["access_token"]}
                import jwt
                import time

                secret = "test-signing-key-for-jwt-only-123456"
                payload = jwt.decode(
                    fresh.json()["access_token"],
                    secret,
                    algorithms=["HS256"],
                    audience="web-admin",
                    issuer="enterprise-rag",
                )
                now = int(time.time())
                payload.update(iat=now - 100, nbf=now - 100, exp=now - 1)
                expired = jwt.encode(payload, secret, algorithm="HS256")
                assert (
                    await client.get("/auth/me", headers={"Authorization": "Bearer " + expired})
                ).status_code == 401
                assert (await client.get("/auth/me", headers=fresh_headers)).status_code == 200
                listing = await client.get("/users?limit=1", headers=headers)
                assert listing.status_code == 200 and len(listing.json()) == 1
                assert "password_hash" not in listing.text
                # Per-client failed-attempt counters are committed independently of request rollback.
                for _ in range(11):
                    throttled = await client.post(
                        "/auth/login", json={"username": prefix, "password": "wrong"}
                    )
                assert throttled.status_code == 429
                assert throttled.headers["retry-after"] == "60"
    finally:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(sa.delete(users).where(users.c.username.startswith(prefix)))
            if family_ids:
                await session.execute(sa.delete(families).where(families.c.id.in_(family_ids)))
            if person_ids:
                await session.execute(sa.delete(persons).where(persons.c.id.in_(person_ids)))
            from app.modules.identity.infrastructure.security import JwtTokens

            await session.execute(
                sa.text("DELETE FROM login_attempts WHERE key = :key"),
                {"key": JwtTokens("test-signing-key-for-jwt-only-123456").digest(prefix)},
            )
        await engine.dispose()


async def test_last_admin_cannot_be_removed() -> None:
    from app.modules.shared.domain.errors import ApplicationError

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            # Shadow only these tables on this connection; never modify actual administrators.
            await session.execute(
                sa.text("CREATE TEMP TABLE users (LIKE public.users INCLUDING ALL) ON COMMIT DROP")
            )
            repository = SqlIdentityRepository(session)
            actor = Principal(uuid4(), "synthetic-admin", UserRole.ADMIN, None)
            await repository.save_user(User(actor, "unused-test-hash"))
            with pytest.raises(ApplicationError, match="last administrator"):
                await repository.update_user(actor.id, UserRole.ADMIN, False, None, None)
            second = Principal(uuid4(), "synthetic-second", UserRole.ADMIN, None)
            await repository.save_user(User(second, "unused-test-hash"))
            await repository.update_user(actor.id, UserRole.ADMIN, False, None, None)
            with pytest.raises(ApplicationError, match="last administrator"):
                await repository.update_user(second.id, UserRole.ADMIN, False, None, None)
    finally:
        await engine.dispose()
