"""Synthetic PNG/JPEG -> real worker/OCR/index -> authorized RAG smoke.

Run inside the checks container after rebuilding API, worker and Web Admin.
Requires the configured Ollama embedding/chat models. Only prints check results.
"""

import asyncio
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.documents.infrastructure.chunk_repository import indexes
from app.modules.documents.infrastructure.extraction_repository import extractions
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.modules.documents.infrastructure.processing_worker import PROCESSING_LOCK
from app.modules.documents.infrastructure.repository import documents
from app.modules.documents.infrastructure.vector_index import QdrantIndex
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository, users
from app.modules.identity.infrastructure.security import JwtTokens


def synthetic_image(directory: Path, extension: str, number: int) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(
        f"BT /F1 16 Tf 72 720 Td (Synthetic image evidence {number}) Tj "
        "0 -30 Td (ORION retention period is 37 days.) Tj ET".encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    source = directory / "source.pdf"
    source.write_bytes(output.getvalue())
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
            "-scale-to",
            "1800",
            "-png" if extension == "png" else "-jpeg",
            str(source),
            str(directory / "image"),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return (directory / ("image.png" if extension == "png" else "image.jpg")).read_bytes()


async def wait_for_jobs(client: httpx.AsyncClient, document_ids: list[str]) -> None:
    async with asyncio.timeout(240):
        while True:
            states = []
            for document_id in document_ids:
                response = await client.get(f"/documents/{document_id}/processing")
                assert response.status_code == 200, response.status_code
                states.append(response.json())
            if all(state["status"] in ("succeeded", "failed") for state in states):
                assert all(state["status"] == "succeeded" for state in states), [
                    (state["status"], state["error_code"]) for state in states
                ]
                return
            await asyncio.sleep(1)


async def main() -> None:
    config = Settings()
    engine = create_engine(config.database_url.get_secret_value())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    family_ids = [uuid4(), uuid4()]
    person_ids, member_ids = [uuid4() for _ in range(3)], [uuid4() for _ in range(3)]
    actors = [
        Principal(uuid4(), "image-smoke-" + uuid4().hex, UserRole.MEMBER, member_id)
        for member_id in member_ids
    ]
    tokens = [
        {"Authorization": "Bearer " + JwtTokens(config.jwt_secret.get_secret_value()).issue(actor)}
        for actor in actors
    ]
    storage = MinioOriginalStorage(
        config.minio_url,
        config.minio_access_key.get_secret_value(),
        config.minio_secret_key.get_secret_value(),
        config.documents_bucket,
    )
    document_ids: list[str] = []
    try:
        async with factory() as session, session.begin():
            for family_id in family_ids:
                await session.execute(
                    sa.insert(families).values(id=family_id, name="Synthetic OCR smoke")
                )
            for i, actor in enumerate(actors):
                await session.execute(
                    sa.insert(persons).values(
                        id=person_ids[i], first_name="Synthetic", last_name="OCR"
                    )
                )
                await session.execute(
                    sa.insert(family_members).values(
                        id=member_ids[i],
                        person_id=person_ids[i],
                        family_id=family_ids[0 if i < 2 else 1],
                    )
                )
                await SqlIdentityRepository(session).save_user(User(actor, "unused-no-login"))
        async with httpx.AsyncClient(
            base_url="http://web-admin:8080/api", timeout=30, headers=tokens[0]
        ) as client:
            response = await client.get("/documents/extraction-formats")
            assert response.status_code == 200
            assert {"image/png", "image/jpeg"}.issubset(response.json())
            with TemporaryDirectory(prefix="rag-image-smoke-") as directory:
                for i, extension in enumerate(("png", "jpg", "jpeg")):
                    content = synthetic_image(Path(directory), extension, i)
                    response = await client.post(
                        "/documents",
                        params={
                            "family_id": str(family_ids[0]),
                            "filename": f"scan.{extension}",
                            "visibility": "private",
                        },
                        headers={
                            "Idempotency-Key": str(uuid4()),
                            "Content-Type": "image/png" if extension == "png" else "image/jpeg",
                        },
                        content=content,
                    )
                    assert response.status_code == 201, response.status_code
                    document_ids.append(response.json()["id"])
                    original = await client.get(f"/documents/{document_ids[-1]}/download")
                    assert original.status_code == 200 and original.content == content
            await wait_for_jobs(client, document_ids)
            for document_id in document_ids:
                response = await client.get(f"/documents/{document_id}/pages")
                assert response.status_code == 200
                pages = response.json()["pages"]
                assert len(pages) == 1 and pages[0]["page_number"] == 1
                assert "ORION" in pages[0]["text"] and "37 days" in pages[0]["text"]
                response = await client.get(f"/documents/{document_id}/index")
                assert response.status_code == 200
                assert response.json()["status"] == "indexed"
                assert response.json()["chunk_count"] >= 1
            print("Member PNG/JPG/JPEG upload -> MinIO -> worker/Tesseract -> index: passed")
            for mode in ("keyword", "vector", "hybrid"):
                body = {
                    "family_id": str(family_ids[0]),
                    "question": "ORION retention period",
                    "retrieval_mode": mode,
                    "top_k": 8,
                }
                response = await client.post("/rag/search", json=body, timeout=85)
                assert response.status_code == 200, response.status_code
                found = response.json()["retrieved_chunks"]
                assert {chunk["document_id"] for chunk in found} == set(document_ids), mode
                assert all(chunk["page_number"] == 1 for chunk in found)
                for i in (1, 2):
                    response = await client.post(
                        "/rag/search", json=body, headers=tokens[i], timeout=85
                    )
                    if i == 1:
                        assert response.status_code == 200
                        assert response.json()["retrieved_chunks"] == []
                    else:
                        assert response.status_code == 404
                    assert "37 days" not in response.text
            for document_id in document_ids:
                for suffix in ("pages", "download"):
                    for token in tokens[1:]:
                        response = await client.get(
                            f"/documents/{document_id}/{suffix}", headers=token
                        )
                        assert response.status_code == 404
            print("Keyword/vector/hybrid retrieval; private and cross-family isolation: passed")
            response = await client.post(
                "/rag/ask",
                json={
                    "family_id": str(family_ids[0]),
                    "question": "ORION retention period",
                    "retrieval_mode": "keyword",
                },
                timeout=85,
            )
            assert response.status_code == 200, (
                response.status_code,
                response.json().get("detail"),
                response.headers.get("X-Request-ID"),
            )
            answer = response.json()
            assert not answer["abstained"] and "37" in answer["answer"], answer["reason"]
            assert answer["citations"] and all(
                item["document_id"] in document_ids and item["page_number"] == 1
                for item in answer["citations"]
            )
            assert answer["trace_id"] == response.headers["X-Request-ID"]
            print("Local model answers from OCR text with image citations and trace ID: passed")
    finally:
        # Wait for an active worker before deleting only this smoke's resources.
        async with engine.begin() as guard:
            await guard.execute(
                sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": PROCESSING_LOCK}
            )
            async with factory() as session:
                originals = (
                    await session.scalars(
                        sa.select(documents.c.object_key).where(
                            documents.c.family_id.in_(family_ids)
                        )
                    )
                ).all()
                artifacts = (
                    await session.scalars(
                        sa.select(extractions.c.artifact_key)
                        .join(documents, documents.c.id == extractions.c.document_id)
                        .where(documents.c.family_id.in_(family_ids))
                    )
                ).all()
                catalog = (
                    (
                        await session.execute(
                            sa.select(indexes)
                            .join(documents, documents.c.id == indexes.c.document_id)
                            .where(documents.c.family_id.in_(family_ids))
                        )
                    )
                    .mappings()
                    .all()
                )
            async with httpx.AsyncClient(timeout=15) as client:
                vectors = QdrantIndex(client, config.qdrant_url)
                for entry in catalog:
                    await vectors.delete_document(
                        entry["collection_name"], family_ids[0], UUID(str(entry["document_id"]))
                    )
            for key in [*originals, *(key for key in artifacts if key)]:
                await storage.delete(key)
            async with factory() as session, session.begin():
                await session.execute(
                    sa.delete(documents).where(documents.c.family_id.in_(family_ids))
                )
                await session.execute(
                    sa.delete(users).where(users.c.id.in_([a.id for a in actors]))
                )
                await session.execute(sa.delete(families).where(families.c.id.in_(family_ids)))
                await session.execute(sa.delete(persons).where(persons.c.id.in_(person_ids)))
        await storage.close()
        await engine.dispose()
        print("Synthetic OCR records, objects and vectors cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
