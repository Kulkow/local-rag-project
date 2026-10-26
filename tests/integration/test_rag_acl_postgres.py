"""Real ACL SQL and HTTP; providers are faked so ordinary tests need no model."""

import os
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import Settings
from app.main import create_app
from app.modules.documents.domain.chunking import ChunkingConfig, chunk_pages
from app.modules.documents.domain.extraction import PageText
from app.modules.documents.application.indexing import IndexRecord
from app.modules.documents.infrastructure.chunk_repository import SqlChunkIndex
from app.modules.documents.infrastructure.repository import documents
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository, users
from app.modules.identity.infrastructure.security import JwtTokens
from app.modules.rag.api.routes import answering_use_case
from app.modules.rag.application.answering import AnswerQuestion, Candidate
from app.modules.rag.infrastructure.evidence_repository import SqlEvidenceRepository

SECRET = "synthetic-rag-signing-key-at-least-32-characters"


async def test_rag_acl_filtering_citations_and_stale_vectors() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to migrated PostgreSQL")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    family_a, family_b = uuid4(), uuid4()
    person_ids, member_ids = [uuid4() for _ in range(3)], [uuid4() for _ in range(3)]
    actors = [
        Principal(uuid4(), "rag-" + uuid4().hex, role, member_ids[i])
        for i, role in enumerate([UserRole.MANAGER, UserRole.MEMBER, UserRole.MEMBER])
    ]
    document_ids = [uuid4() for _ in range(3)]
    chunks = []
    try:
        async with factory() as session, session.begin():
            await session.execute(
                sa.insert(families),
                [
                    {"id": family_a, "name": "Synthetic RAG A"},
                    {"id": family_b, "name": "Synthetic RAG B"},
                ],
            )
            for i, actor in enumerate(actors):
                await session.execute(
                    sa.insert(persons).values(
                        id=person_ids[i], first_name="Synthetic", last_name="RAG"
                    )
                )
                await session.execute(
                    sa.insert(family_members).values(
                        id=member_ids[i],
                        person_id=person_ids[i],
                        family_id=family_a if i < 2 else family_b,
                    )
                )
                await SqlIdentityRepository(session).save_user(User(actor, "unused-fixture"))
            for i, text in enumerate(
                ["PRIVATEALPHASECRET", "ORION retention period is 37 days.", "FAMILYBETASECRET"]
            ):
                document_id = document_ids[i]
                await session.execute(
                    sa.insert(documents).values(
                        id=document_id,
                        family_id=family_a if i < 2 else family_b,
                        owner_id=actors[0 if i < 2 else 2].id,
                        filename=f"synthetic-{i}.pdf",
                        content_type="application/pdf",
                        size_bytes=10,
                        checksum="a" * 64,
                        object_key="synthetic-rag/" + str(document_id),
                        visibility="private" if i == 0 else "family",
                        status="uploaded",
                    )
                )
                chunks.append(
                    chunk_pages(document_id, "a" * 64, (PageText(1, text),), ChunkingConfig())
                )
        for i, document_id in enumerate(document_ids):
            record = IndexRecord(
                document_id, uuid4(), "a" * 64, "indexing", "synthetic", "synthetic", "digest", 3
            )
            repository = SqlChunkIndex(factory)
            await repository.start(record, uuid4(), "a" * 64, ChunkingConfig())
            await repository.complete(record, chunks[i])
        embeddings, vectors, chat = AsyncMock(), AsyncMock(), AsyncMock()
        embeddings.model, embeddings.dimensions = "synthetic", 3
        embeddings.identity.return_value = "digest"
        embeddings.embed.return_value = [[1.0, 0.0, 0.0]]
        chat.answer.return_value = {
            "answer": "37 days [1].",
            "citations": [1],
            "insufficient_evidence": False,
        }
        use_case = AnswerQuestion(SqlEvidenceRepository(factory), embeddings, vectors, chat)
        app = create_app(
            Settings(
                database_url=url,
                jwt_secret=SECRET,
                admin_username="test-admin",
                admin_password="synthetic-password",
            )
        )
        app.dependency_overrides[answering_use_case] = lambda: use_case
        tokens = [{"Authorization": "Bearer " + JwtTokens(SECRET).issue(actor)} for actor in actors]
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            body = {
                "family_id": str(family_a),
                "question": "ORION retention",
                "retrieval_mode": "keyword",
            }
            assert (await client.post("/rag/ask", json=body)).status_code == 401
            assert (await client.post("/rag/ask", headers=tokens[2], json=body)).status_code == 404
            result = await client.post("/rag/ask", headers=tokens[1], json=body)
            assert result.status_code == 200, result.text
            assert not result.json()["abstained"]
            assert result.json()["citations"][0]["document_id"] == str(document_ids[1])
            assert result.json()["trace_id"] == result.headers["X-Request-ID"]
            assert "PRIVATEALPHA" not in result.text and "FAMILYBETA" not in result.text
            # A poisoned/stale vector response cannot bypass live SQL authorization.
            scopes = await use_case.repository.scopes(actors[0], family_a)
            visible = await use_case.repository.scopes(actors[1], family_a)
            assert [scope.document_id for scope in visible] == [document_ids[1]]
            assert len(scopes) == 2
            generation = {scope.document_id: scope.generation for scope in scopes}
            vectors.search.return_value = [
                Candidate(chunks[0][0].id, document_ids[0], generation[document_ids[0]], 0.99),
                Candidate(chunks[1][0].id, document_ids[1], generation[document_ids[1]], 0.9),
                Candidate(chunks[2][0].id, document_ids[2], uuid4(), 0.98),
            ]
            result = await client.post(
                "/rag/ask", headers=tokens[1], json={**body, "retrieval_mode": "vector"}
            )
            assert result.status_code == 200, result.text
            assert [source["document_id"] for source in result.json()["retrieved_chunks"]] == [
                str(document_ids[1])
            ]
            assert [scope.document_id for scope in vectors.search.await_args.args[1]] == [
                document_ids[1]
            ]
            assert "PRIVATEALPHA" not in result.text and "FAMILYBETA" not in result.text
            chat.reset_mock()
            vectors.search.return_value = [
                Candidate(chunks[1][0].id, document_ids[1], uuid4(), 0.99)
            ]
            result = await client.post(
                "/rag/ask", headers=tokens[1], json={**body, "retrieval_mode": "vector"}
            )
            assert result.json()["abstained"] and result.json()["retrieved_chunks"] == []
            chat.answer.assert_not_awaited()
            unknown = await client.post(
                "/rag/ask",
                headers=tokens[1],
                json={**body, "question": "PRIVATEALPHASECRET FAMILYBETASECRET"},
            )
            assert unknown.json()["abstained"] and unknown.json()["retrieved_chunks"] == []
            assert (
                await client.post("/rag/ask", headers=tokens[1], json={**body, "question": "  "})
            ).status_code == 422
    finally:
        async with factory() as session, session.begin():
            await session.execute(sa.delete(documents).where(documents.c.id.in_(document_ids)))
            await session.execute(
                sa.delete(users).where(users.c.id.in_([actor.id for actor in actors]))
            )
            await session.execute(
                sa.delete(families).where(families.c.id.in_([family_a, family_b]))
            )
            await session.execute(sa.delete(persons).where(persons.c.id.in_(person_ids)))
        await engine.dispose()
