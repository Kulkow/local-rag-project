"""Verify a >10 MiB batch through Nginx using a synthetic member and MinIO."""

import asyncio
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.modules.documents.infrastructure.repository import documents
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository, users
from app.modules.identity.infrastructure.security import JwtTokens


async def main() -> None:
    config = Settings()
    engine = create_engine(config.database_url.get_secret_value())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    family_id, person_id, member_id = uuid4(), uuid4(), uuid4()
    actor = Principal(uuid4(), "batch-smoke-" + uuid4().hex, UserRole.MEMBER, member_id)
    storage = MinioOriginalStorage(
        config.minio_url,
        config.minio_access_key.get_secret_value(),
        config.minio_secret_key.get_secret_value(),
        config.documents_bucket,
    )
    object_keys: list[str] = []
    try:
        async with factory() as session, session.begin():
            await session.execute(sa.insert(families).values(id=family_id, name="Synthetic batch"))
            await session.execute(
                sa.insert(persons).values(id=person_id, first_name="Synthetic", last_name="Batch")
            )
            await session.execute(
                sa.insert(family_members).values(
                    id=member_id, person_id=person_id, family_id=family_id
                )
            )
            await SqlIdentityRepository(session).save_user(User(actor, "unused-no-login"))
        token = JwtTokens(config.jwt_secret.get_secret_value()).issue(actor)
        async with httpx.AsyncClient(
            base_url="http://web-admin:8080/api",
            timeout=60,
            headers={"Authorization": "Bearer " + token, "Content-Type": "text/html"},
        ) as client:
            for number in range(2):
                content = (
                    b"<html><body>"
                    + str(number).encode()
                    + b"x" * (6 * 1024 * 1024)
                    + b"</body></html>"
                )
                params = {"family_id": str(family_id), "filename": f"batch-{number}.html"}
                headers = {"Idempotency-Key": str(uuid4())}
                response = await client.post(
                    "/documents", params=params, headers=headers, content=content
                )
                assert response.status_code == 201, response.status_code
                document_id = UUID(response.json()["id"])
                object_key = f"originals/{family_id}/{document_id}"
                object_keys.append(object_key)
                assert await storage.get(object_key, len(content)) == content
                replay = await client.post(
                    "/documents", params=params, headers=headers, content=content
                )
                assert replay.status_code == 201 and replay.json()["id"] == str(document_id)
                duplicate = await client.post(
                    "/documents",
                    params=params,
                    headers={"Idempotency-Key": str(uuid4())},
                    content=content,
                )
                assert duplicate.status_code == 409
            oversized = await client.post(
                "/documents",
                params={"family_id": str(family_id), "filename": "too-large.html"},
                headers={"Idempotency-Key": str(uuid4())},
                content=b"x" * (10 * 1024 * 1024 + 1),
            )
            assert oversized.status_code == 413
            async with factory() as session:
                count = await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(documents)
                    .where(documents.c.owner_id == actor.id)
                )
                assert count == 2
            print(
                "Member uploaded >12 MiB in two requests through Nginx; MinIO bytes verified: passed"
            )
            print("Per-file 10 MiB limit, duplicate rejection and idempotent retries: passed")
    finally:
        # Query the scope as well, so cleanup handles an interrupted HTTP response.
        async with factory() as session:
            keys = (
                (
                    await session.execute(
                        sa.select(documents.c.object_key).where(documents.c.owner_id == actor.id)
                    )
                )
                .scalars()
                .all()
            )
        try:
            for key in set(object_keys) | set(keys):
                await storage.delete(key)
            async with factory() as session, session.begin():
                await session.execute(sa.delete(documents).where(documents.c.owner_id == actor.id))
                await session.execute(sa.delete(users).where(users.c.id == actor.id))
                await session.execute(sa.delete(families).where(families.c.id == family_id))
                await session.execute(sa.delete(persons).where(persons.c.id == person_id))
            print("Synthetic batch records and objects cleaned up")
        finally:
            await storage.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
