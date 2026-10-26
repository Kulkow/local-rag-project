"""Synthetic real-worker E2E; print only sanitized verification results."""

import asyncio
import io
import os
from uuid import uuid4

import httpx
import sqlalchemy as sa
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.modules.documents.infrastructure.repository import documents
from app.modules.documents.infrastructure.extraction_repository import extractions
from app.modules.documents.infrastructure.chunk_repository import indexes
from app.modules.documents.infrastructure.vector_index import QdrantIndex
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository, users
from app.modules.identity.infrastructure.security import JwtTokens


def pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 20 200 Td ("
        + b"Synthetic queue evidence. The retention period for project ORION is 37 days. " * 40
        + b") Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


async def main() -> None:
    config = Settings()
    engine = create_engine(config.database_url.get_secret_value())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    member_id = uuid4() if os.getenv("SMOKE_MEMBER") == "1" else None
    person_id = uuid4() if member_id else None
    actor = Principal(
        uuid4(),
        "queue-smoke-" + uuid4().hex,
        UserRole.MEMBER if member_id else UserRole.ADMIN,
        member_id,
    )
    family_id = uuid4()
    ids = []
    storage = MinioOriginalStorage(
        config.minio_url,
        config.minio_access_key.get_secret_value(),
        config.minio_secret_key.get_secret_value(),
        config.documents_bucket,
    )
    try:
        async with factory() as session, session.begin():
            await session.execute(
                sa.insert(families).values(id=family_id, name="Synthetic queue smoke")
            )
            if member_id:
                await session.execute(
                    sa.insert(persons).values(
                        id=person_id, first_name="Synthetic", last_name="Queue member"
                    )
                )
                await session.execute(
                    sa.insert(family_members).values(
                        id=member_id, person_id=person_id, family_id=family_id
                    )
                )
            await SqlIdentityRepository(session).save_user(User(actor, "unused-no-login"))
        token = JwtTokens(config.jwt_secret.get_secret_value()).issue(actor)
        async with httpx.AsyncClient(
            base_url="http://api:8000", timeout=20, headers={"Authorization": "Bearer " + token}
        ) as client:
            for i, content in enumerate(
                [pdf(), pdf() + b"\n% second synthetic original\n", b"%PDF-1.4\n%%EOF\n"]
            ):
                response = await client.post(
                    "/documents",
                    params={
                        "family_id": str(family_id),
                        "filename": f"synthetic-{i}.pdf",
                        "visibility": "private",
                    },
                    headers={"Idempotency-Key": str(uuid4()), "Content-Type": "application/pdf"},
                    content=content,
                )
                assert response.status_code == 201, response.status_code
                ids.append(response.json()["id"])
            duplicate = await client.post(
                "/documents",
                params={
                    "family_id": str(family_id),
                    "filename": "renamed.pdf",
                    "visibility": "family",
                },
                headers={"Idempotency-Key": str(uuid4()), "Content-Type": "application/pdf"},
                content=pdf(),
            )
            assert duplicate.status_code == 409, duplicate.status_code
            print("Same-owner duplicate upload rejected with HTTP 409: passed")
            states = []
            for _ in range(240):
                states = [(await client.get(f"/documents/{id}/processing")).json() for id in ids]
                if all(state["status"] in ("succeeded", "failed") for state in states):
                    break
                await asyncio.sleep(1)
            assert [s["status"] for s in states] == ["succeeded", "succeeded", "failed"], states
            assert states[2]["attempts"] == 1 and states[2]["error_code"] == "invalid"
            metadata = await client.get("/documents", params={"family_id": str(family_id)})
            assert metadata.status_code == 200
            titles = {item["id"]: item["title"] for item in metadata.json()}
            assert all(
                titles[id]
                and titles[id].startswith("Synthetic queue evidence.")
                and len(titles[id]) <= 255
                for id in ids[:2]
            )
            assert titles[ids[2]] is None
            print(
                "Worker persists transcript-derived titles; failed extraction keeps title null: passed"
            )
            ordered = sorted(states, key=lambda s: s["started_at"])
            assert all(b["started_at"] >= a["finished_at"] for a, b in zip(ordered, ordered[1:]))
            for id in ids[:2]:
                response = await client.get(f"/documents/{id}/pages")
                assert response.status_code == 200
                assert "Synthetic queue evidence" in response.json()["pages"][0]["text"]
            for id in ids[:2]:
                response = await client.get(f"/documents/{id}/index")
                assert response.status_code == 200
                state = response.json()
                assert state["status"] == "indexed" and state["chunk_count"] >= 2
                assert state["dimensions"] == config.embedding_dimensions
            # Rebuild explicitly to exercise stable IDs and stale-vector cleanup.
            response = await client.post(f"/documents/{ids[0]}/reindex")
            assert response.status_code == 202
            for _ in range(120):
                response = await client.get(f"/documents/{ids[0]}/processing")
                if response.json()["status"] in ("succeeded", "failed"):
                    break
                await asyncio.sleep(1)
            assert response.json()["status"] == "succeeded"
            async with factory() as session:
                catalog = (
                    (
                        await session.execute(
                            sa.select(indexes).where(indexes.c.document_id.in_(ids[:2]))
                        )
                    )
                    .mappings()
                    .all()
                )
            async with httpx.AsyncClient(timeout=20) as vector_client:
                for entry in catalog:
                    response = await vector_client.post(
                        config.qdrant_url + f"/collections/{entry['collection_name']}/points/count",
                        json={
                            "exact": True,
                            "filter": {
                                "must": [
                                    {"key": "family_id", "match": {"value": str(family_id)}},
                                    {
                                        "key": "document_id",
                                        "match": {"value": str(entry["document_id"])},
                                    },
                                ]
                            },
                        },
                    )
                    assert response.status_code == 200
                    assert response.json()["result"]["count"] == entry["chunk_count"]
            for mode, question in [
                ("keyword", "ORION retention"),
                ("vector", "What is the retention period for project ORION?"),
                ("hybrid", "ORION retention period"),
            ]:
                response = await client.post(
                    "/rag/ask",
                    json={
                        "family_id": str(family_id),
                        "question": question,
                        "retrieval_mode": mode,
                        "top_k": 3,
                    },
                    timeout=85,
                )
                assert response.status_code == 200, response.status_code
                answer = response.json()
                assert not answer["abstained"] and "37" in answer["answer"], answer["reason"]
                assert answer["citations"] and all(
                    source["document_id"] in ids[:2] for source in answer["citations"]
                )
                assert answer["trace_id"] == response.headers["X-Request-ID"]
                if mode == "hybrid":
                    assert "rrf_ms" in answer["timings"]
                    assert type(answer["reranked"]) is bool
            response = await client.post(
                "/rag/ask",
                json={
                    "family_id": str(family_id),
                    "question": "QZXUNANSWERABLE987",
                    "retrieval_mode": "keyword",
                },
                timeout=85,
            )
            assert response.json()["abstained"] and response.json()["retrieved_chunks"] == []
            assert response.json()["reason"] == "no_evidence"
            assert "не нашёл подходящих фрагментов" in response.json()["answer"]
            proxy_response = await client.post(
                "http://web-admin:8080/api/rag/search",
                json={
                    "family_id": str(family_id),
                    "question": "ORION retention",
                    "retrieval_mode": "keyword",
                },
                timeout=20,
            )
            assert proxy_response.status_code == 200 and proxy_response.json()["retrieved_chunks"]
            assert (await client.get("http://web-admin:8080/rag")).status_code == 200
            original = await client.get(f"http://web-admin:8080/api/documents/{ids[0]}/download")
            assert original.status_code == 200 and original.content == pdf()
            assert original.headers["Content-Disposition"].startswith("attachment;")
            assert original.headers["Cache-Control"] == "no-store"
            print("Authorized source download through Nginx matches original PDF bytes: passed")
            metrics_response = await client.get("/internal/metrics")
            assert metrics_response.status_code == 200
            assert 'stage="vector_search"' in metrics_response.text
            assert 'stage="keyword_search"' in metrics_response.text
            assert 'stage="generation"' in metrics_response.text
            assert 'outcome="abstained"' in metrics_response.text
            assert not any(id in metrics_response.text for id in ids)
            assert (
                "ORION" not in metrics_response.text
                and "synthetic-0.pdf" not in metrics_response.text
            )
            assert (
                await client.get("http://web-admin:8080/api/internal/metrics")
            ).status_code == 404
            print(
                "RAG stage histograms, outcomes, privacy and blocked browser metrics proxy: passed"
            )
            print("Web Admin SPA route and authenticated Nginx RAG proxy: passed")
            print(
                "Live keyword/vector/hybrid RAG, local chat answer with citations and no-evidence abstention: passed"
            )
            print(
                "Live chunk catalog, Ollama embeddings, Qdrant vectors and duplicate-free reindex: passed"
            )
            print("Live API -> PostgreSQL/MinIO -> Celery worker -> extracted pages: passed")
            print(
                "Two successful documents processed sequentially; invalid PDF failed after one attempt: passed"
            )
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("http://queue-metrics:9100/metrics")
            assert response.status_code == 200
            assert "rag_document_worker_heartbeat 1" in response.text
            assert not any(id in response.text for id in ids)
            for _ in range(20):
                query = await client.get(
                    "http://prometheus:9090/api/v1/query",
                    params={"query": 'up{job="document-processing"}'},
                )
                data = query.json()["data"]["result"]
                if data and data[0]["value"][1] == "1":
                    break
                await asyncio.sleep(1)
            assert data and data[0]["value"][1] == "1"
            for _ in range(30):
                query = await client.get(
                    "http://prometheus:9090/api/v1/query",
                    params={
                        "query": 'sum(rag_stage_duration_seconds_count{stage="vector_search"})'
                    },
                )
                rag_data = query.json()["data"]["result"]
                if rag_data and float(rag_data[0]["value"][1]) >= 1:
                    break
                await asyncio.sleep(1)
            assert rag_data and float(rag_data[0]["value"][1]) >= 1
            print("Actual Prometheus scrape contains executed RAG stages: passed")
            print("Exporter heartbeat/privacy and actual Prometheus scrape: passed")
            response = await client.get(
                "http://grafana:3000/api/dashboards/uid/document-processing",
                auth=(
                    os.getenv("GRAFANA_ADMIN_USER") or config.admin_username,
                    os.getenv("GRAFANA_ADMIN_PASSWORD") or config.admin_password.get_secret_value(),
                ),
            )
            assert response.status_code == 200, response.status_code
            assert len(response.json()["dashboard"]["panels"]) == 9
            print("Authenticated provisioned Grafana dashboard: passed")
            response = await client.get(
                "http://grafana:3000/api/dashboards/uid/rag-performance",
                auth=(
                    os.getenv("GRAFANA_ADMIN_USER") or config.admin_username,
                    os.getenv("GRAFANA_ADMIN_PASSWORD") or config.admin_password.get_secret_value(),
                ),
            )
            assert response.status_code == 200
            assert any(
                "rag_stage_duration_seconds_bucket" in target.get("expr", "")
                for panel in response.json()["dashboard"]["panels"]
                for target in panel.get("targets", [])
            )
            for panel in response.json()["dashboard"]["panels"]:
                for target in panel.get("targets", []):
                    query = await client.get(
                        "http://prometheus:9090/api/v1/query", params={"query": target["expr"]}
                    )
                    assert query.status_code == 200 and query.json()["status"] == "success"
            print("All RAG dashboard PromQL expressions accepted by Prometheus: passed")
            print("Authenticated provisioned RAG Performance dashboard: passed")
    finally:
        async with factory() as session:
            originals = (
                (
                    await session.execute(
                        sa.select(documents.c.object_key).where(documents.c.family_id == family_id)
                    )
                )
                .scalars()
                .all()
            )
            artifacts = (
                (
                    await session.execute(
                        sa.select(extractions.c.artifact_key)
                        .join(documents, documents.c.id == extractions.c.document_id)
                        .where(documents.c.family_id == family_id)
                    )
                )
                .scalars()
                .all()
            )
        async with factory() as session:
            catalog = (
                (
                    await session.execute(
                        sa.select(indexes)
                        .join(documents, documents.c.id == indexes.c.document_id)
                        .where(documents.c.family_id == family_id)
                    )
                )
                .mappings()
                .all()
            )
        async with httpx.AsyncClient(timeout=15) as client:
            vector_index = QdrantIndex(client, config.qdrant_url)
            for entry in catalog:
                await vector_index.delete_document(
                    entry["collection_name"], family_id, entry["document_id"]
                )
        for key in list(originals) + [key for key in artifacts if key]:
            await storage.delete(key)
        async with factory() as session, session.begin():
            await session.execute(sa.delete(documents).where(documents.c.family_id == family_id))
            await session.execute(sa.delete(users).where(users.c.id == actor.id))
            await session.execute(sa.delete(families).where(families.c.id == family_id))
            if person_id:
                await session.execute(sa.delete(persons).where(persons.c.id == person_id))
        await storage.close()
        await engine.dispose()
        print("Synthetic records and objects cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
