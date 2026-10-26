"""Upload API with PostgreSQL; storage contract also has an opt-in live MinIO test."""

import asyncio
from dataclasses import replace
from collections.abc import AsyncIterator
import os
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.document_dependencies import ScopedFamilyAccess, upload_use_case
from app.core.settings import Settings
from app.main import create_app
from app.modules.documents.domain.entities import DocumentStatus
from app.modules.documents.application.upload import UploadDocument
from app.modules.documents.infrastructure.repository import SqlDocumentRepository, documents
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.modules.families.infrastructure.persistence import families, family_members, persons
from app.modules.identity.domain.entities import Principal, User, UserRole
from app.modules.identity.infrastructure.repository import SqlIdentityRepository, users
from app.modules.identity.infrastructure.security import JwtTokens

PDF = b"%PDF-1.4\n% synthetic upload fixture\n%%EOF\n"
SECRET = "test-signing-key-for-jwt-only-123456"


@pytest.fixture(autouse=True)
async def pause_live_document_consumer() -> AsyncIterator[None]:
    """Keep a real local worker from consuming fake-storage fixtures during API tests."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        yield
        return
    from app.modules.documents.infrastructure.processing_worker import PROCESSING_LOCK

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": PROCESSING_LOCK}
            )
            yield
    finally:
        await engine.dispose()


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.failed = False
        self.block: asyncio.Event | None = None
        self.started = asyncio.Event()

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.started.set()
        if self.block:
            await self.block.wait()
        if self.failed:
            raise OSError("synthetic unavailable object storage")
        self.objects[key] = content

    async def get(self, key: str, max_bytes: int) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


async def test_document_upload_api_acl_idempotency_and_failures() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to migrated PostgreSQL")
    engine = create_async_engine(url)
    prefix = "document-test-" + uuid4().hex
    family, other_family = uuid4(), uuid4()
    person_ids, member_ids = [uuid4() for _ in range(3)], [uuid4() for _ in range(3)]
    actors = [Principal(uuid4(), prefix + "admin", UserRole.ADMIN, None)]
    actors += [
        Principal(
            uuid4(), prefix + str(i), UserRole.MEMBER if i == 2 else UserRole.MANAGER, member_ids[i]
        )
        for i in range(3)
    ]
    storage = MemoryStorage()
    try:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(
                sa.insert(families),
                [
                    {"id": family, "name": "Synthetic documents"},
                    {"id": other_family, "name": "Other documents"},
                ],
            )
            for person_id, member_id in zip(person_ids, member_ids, strict=True):
                await session.execute(
                    sa.insert(persons).values(
                        id=person_id, first_name="Synthetic", last_name=prefix
                    )
                )
                await session.execute(
                    sa.insert(family_members).values(
                        id=member_id, person_id=person_id, family_id=family
                    )
                )
            for actor in actors:
                await SqlIdentityRepository(session).save_user(
                    User(actor, "unused-no-login-fixture")
                )
        app = create_app(
            Settings(
                database_url=url,
                jwt_secret=SECRET,
                admin_username="test-admin",
                admin_password="synthetic-password",
            )
        )
        async with app.router.lifespan_context(app):
            from app.api.document_dependencies import (
                extract_document_use_case,
                read_extracted_pages_use_case,
            )
            from app.modules.documents.application.extraction import (
                ExtractDocument,
                ReadExtractedPages,
            )
            from app.modules.documents.infrastructure.extraction_repository import (
                SqlExtractionRepository,
            )

            factory = app.state.db_session_factory
            from app.api.document_dependencies import download_document_use_case
            from app.modules.documents.application.download import DownloadDocument

            app.dependency_overrides[download_document_use_case] = lambda: DownloadDocument(
                SqlExtractionRepository(factory), storage, ScopedFamilyAccess(factory)
            )
            app.dependency_overrides[extract_document_use_case] = lambda: ExtractDocument(
                SqlExtractionRepository(factory),
                storage,
                app.state.extractors,
                ScopedFamilyAccess(factory),
            )
            app.dependency_overrides[read_extracted_pages_use_case] = lambda: ReadExtractedPages(
                SqlExtractionRepository(factory), storage, ScopedFamilyAccess(factory)
            )
            app.dependency_overrides[upload_use_case] = lambda: UploadDocument(
                SqlDocumentRepository(factory), storage, ScopedFamilyAccess(factory)
            )
            headers = [
                {"Authorization": "Bearer " + JwtTokens(SECRET).issue(actor)} for actor in actors
            ]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = f"/documents?family_id={family}&filename=guide.pdf&visibility=private"
                key = str(uuid4())
                upload_headers = {
                    **headers[1],
                    "Content-Type": "application/pdf",
                    "Idempotency-Key": key,
                }
                assert (await client.post(path, content=PDF)).status_code == 401
                forbidden = f"/documents?family_id={other_family}&filename=guide.pdf"
                assert (
                    await client.post(forbidden, headers=upload_headers, content=PDF)
                ).status_code == 404
                assert (
                    await client.post(
                        forbidden, headers={**upload_headers, **headers[3]}, content=PDF
                    )
                ).status_code == 404
                assert not storage.objects
                response = await client.post(path, headers=upload_headers, content=PDF)
                assert response.status_code == 201, response.text
                document_id = response.json()["id"]
                assert response.json()["status"] == "uploaded"
                assert response.headers["X-Request-ID"]
                assert "object_key" not in response.json()
                assert next(iter(storage.objects.values())) == PDF
                replay = await client.post(path, headers=upload_headers, content=PDF)
                assert replay.status_code == 201 and replay.json()["id"] == document_id
                assert len(storage.objects) == 1
                # New keys/names/ACL cannot bypass per-owner content deduplication.
                for duplicate_path in (
                    path,
                    path.replace("guide.pdf", "renamed.pdf"),
                    path.replace("private", "family"),
                ):
                    duplicate = await client.post(
                        duplicate_path,
                        headers={**upload_headers, "Idempotency-Key": str(uuid4())},
                        content=PDF,
                    )
                    assert duplicate.status_code == 409, duplicate.text
                    assert "already uploaded" in duplicate.json()["detail"]
                assert len(storage.objects) == 1
                downloaded = await client.get(
                    f"/documents/{document_id}/download", headers=headers[1]
                )
                assert downloaded.status_code == 200 and downloaded.content == PDF
                assert downloaded.headers["Content-Disposition"].startswith("attachment;")
                assert downloaded.headers["Cache-Control"] == "no-store"
                assert downloaded.headers["Content-Type"] == "application/octet-stream"
                assert (await client.get(f"/documents/{document_id}/download")).status_code == 401
                assert (
                    await client.get(f"/documents/{document_id}/download", headers=headers[2])
                ).status_code == 404
                queued = await client.get(
                    f"/documents/{document_id}/processing", headers=headers[1]
                )
                assert queued.status_code == 200, queued.text
                assert (
                    await client.get(f"/documents/{document_id}/index", headers=headers[2])
                ).status_code == 404
                assert (
                    await client.post(f"/documents/{document_id}/reindex", headers=headers[2])
                ).status_code == 404
                assert queued.json()["status"] == "queued" and queued.json()["attempts"] == 0
                assert (
                    await client.post(f"/documents/{document_id}/process", headers=headers[2])
                ).status_code == 404
                assert (
                    await client.get(f"/documents/{document_id}/processing", headers=headers[2])
                ).status_code == 404
                repeated_job = await client.post(
                    f"/documents/{document_id}/process", headers=headers[1]
                )
                assert repeated_job.status_code == 202 and repeated_job.json()["attempts"] == 0
                # A delayed failure from an old caller must not downgrade a completed upload.
                repository = SqlDocumentRepository(app.state.db_session_factory)
                saved = (await repository.list(actors[1], family, 0, 20))[0]
                await repository.fail(
                    replace(saved, status=DocumentStatus.UPLOADING), "storage_unavailable"
                )
                unchanged = (await repository.list(actors[1], family, 0, 20))[0]
                assert unchanged.status == DocumentStatus.UPLOADED
                assert unchanged.error_code is None
                assert (
                    await client.post(f"/documents/{document_id}/extract", headers=headers[2])
                ).status_code == 404
                assert (
                    await client.get(f"/documents/{document_id}/pages", headers=headers[2])
                ).status_code == 404
                extraction = await client.post(
                    f"/documents/{document_id}/extract", headers=headers[1]
                )
                assert extraction.status_code == 422, extraction.text
                state = await client.get(f"/documents/{document_id}/extraction", headers=headers[1])
                assert (
                    state.json()["status"] == "failed"
                    and state.json()["error_code"] == "pdf_invalid"
                )
                assert (
                    await client.post(path, headers=upload_headers, content=PDF + b"changed")
                ).status_code == 409
                for actor_headers, expected in (
                    (headers[0], 1),
                    (headers[1], 1),
                    (headers[2], 0),
                    (headers[3], 0),
                ):
                    listing = await client.get(
                        f"/documents?family_id={family}", headers=actor_headers
                    )
                    assert listing.status_code == 200
                    assert len(listing.json()) == expected
                assert (
                    await client.get(f"/documents?family_id={other_family}", headers=headers[1])
                ).status_code == 404
                shared = await client.post(
                    path.replace("private", "family"),
                    headers={**upload_headers, "Idempotency-Key": str(uuid4())},
                    content=PDF + b"shared",
                )
                assert shared.status_code == 201
                shared_id = shared.json()["id"]
                assert (
                    await client.post(f"/documents/{shared_id}/reindex", headers=headers[3])
                ).status_code == 403
                assert (
                    await client.post(f"/documents/{shared_id}/process", headers=headers[3])
                ).status_code == 403
                assert (
                    await client.get(f"/documents/{shared_id}/processing", headers=headers[3])
                ).status_code == 200
                assert (
                    await client.post(f"/documents/{shared_id}/extract", headers=headers[3])
                ).status_code == 403
                assert (
                    await client.get(f"/documents/{shared_id}/pages", headers=headers[3])
                ).status_code == 409
                assert (
                    len(
                        (
                            await client.get(f"/documents?family_id={family}", headers=headers[3])
                        ).json()
                    )
                    == 1
                )
                assert (
                    await client.post(
                        path, headers={**upload_headers, "Content-Type": "text/html"}, content=PDF
                    )
                ).status_code == 415
                assert (
                    await client.post(
                        path.replace("guide.pdf", "../guide.pdf"),
                        headers=upload_headers,
                        content=PDF,
                    )
                ).status_code == 422
                assert (
                    await client.post(
                        path, headers={**upload_headers, "Content-Length": "10485761"}, content=PDF
                    )
                ).status_code == 413

                async def oversized_body():
                    yield PDF
                    yield b"x" * 10485760

                assert (
                    await client.post(path, headers=upload_headers, content=oversized_body())
                ).status_code == 413
                assert (
                    await client.post(
                        path, headers={**upload_headers, "Idempotency-Key": "invalid"}, content=PDF
                    )
                ).status_code == 422
                storage.failed = True
                failed_headers = {**upload_headers, "Idempotency-Key": str(uuid4())}
                assert (
                    await client.post(path, headers=failed_headers, content=PDF + b"failure")
                ).status_code == 503
                failed = (
                    await client.get(f"/documents?family_id={family}", headers=headers[1])
                ).json()
                assert any(doc["status"] == "upload_failed" for doc in failed)
                storage.failed = False
                assert (
                    await client.post(path, headers=failed_headers, content=PDF + b"failure")
                ).status_code == 201
                failed_duplicate = await client.post(
                    path,
                    headers={**upload_headers, "Idempotency-Key": str(uuid4())},
                    content=PDF + b"failure",
                )
                assert failed_duplicate.status_code == 409
                # Members upload within their family and retain ownership through processing.
                member_upload = await client.post(
                    path,
                    headers={**upload_headers, **headers[3], "Idempotency-Key": str(uuid4())},
                    content=PDF,
                )
                assert member_upload.status_code == 201, member_upload.text
                member_id = member_upload.json()["id"]
                assert member_upload.json()["owner_id"] == str(actors[3].id)
                assert (
                    await client.post(f"/documents/{member_id}/process", headers=headers[3])
                ).status_code == 202
                assert (
                    await client.post(f"/documents/{member_id}/reindex", headers=headers[3])
                ).status_code == 202
                # Synthetic malformed PDF reaches the parser (422), rather than a role denial.
                assert (
                    await client.post(f"/documents/{member_id}/extract", headers=headers[3])
                ).status_code == 422
                hidden = (
                    await client.get(f"/documents?family_id={family}", headers=headers[2])
                ).json()
                assert member_id not in [item["id"] for item in hidden]
                # Deduplication covers all families of an owner, but not other owners.
                admin_headers = {**upload_headers, **headers[0], "Idempotency-Key": str(uuid4())}
                assert (
                    await client.post(path, headers=admin_headers, content=PDF)
                ).status_code == 201
                assert (
                    await client.post(
                        path.replace(str(family), str(other_family)),
                        headers={**admin_headers, "Idempotency-Key": str(uuid4())},
                        content=PDF,
                    )
                ).status_code == 409
                foreign = await client.post(
                    path.replace(str(family), str(other_family)),
                    headers={**admin_headers, "Idempotency-Key": str(uuid4())},
                    content=PDF + b"foreign",
                )
                assert foreign.status_code == 201
                assert (
                    await client.get(
                        f"/documents/{foreign.json()['id']}/download", headers=headers[1]
                    )
                ).status_code == 404
                shared_download = await client.get(
                    f"/documents/{shared_id}/download", headers=headers[3]
                )
                assert (
                    shared_download.status_code == 200
                    and shared_download.content == PDF + b"shared"
                )
                # Reserve commits before I/O, so a concurrent request cannot duplicate the object.
                storage.block = asyncio.Event()
                storage.started.clear()
                concurrent_headers = {**upload_headers, "Idempotency-Key": str(uuid4())}
                first = asyncio.create_task(
                    client.post(path, headers=concurrent_headers, content=PDF + b"concurrent")
                )
                try:
                    await asyncio.wait_for(storage.started.wait(), timeout=5)
                    assert (
                        await client.post(
                            path, headers=concurrent_headers, content=PDF + b"concurrent"
                        )
                    ).status_code == 409
                    # A different key must also fail while the first original is uploading.
                    assert (
                        await client.post(
                            path.replace("guide.pdf", "copy.pdf"),
                            headers={**concurrent_headers, "Idempotency-Key": str(uuid4())},
                            content=PDF + b"concurrent",
                        )
                    ).status_code == 409
                finally:
                    storage.block.set()
                    assert (await first).status_code == 201
                storage.block = None
                simultaneous = await asyncio.gather(
                    *(
                        client.post(
                            path,
                            headers={**upload_headers, "Idempotency-Key": str(uuid4())},
                            content=PDF + b"simultaneous",
                        )
                        for _ in range(2)
                    )
                )
                assert sorted(result.status_code for result in simultaneous) == [201, 409]
    finally:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(
                sa.delete(documents).where(documents.c.family_id.in_([family, other_family]))
            )
            await session.execute(
                sa.delete(users).where(users.c.id.in_([actor.id for actor in actors]))
            )
            await session.execute(
                sa.delete(families).where(families.c.id.in_([family, other_family]))
            )
            await session.execute(sa.delete(persons).where(persons.c.id.in_(person_ids)))
        await engine.dispose()


async def test_live_minio_original_storage() -> None:
    if os.getenv("TEST_OBJECT_STORAGE") != "1":
        pytest.skip("Set TEST_OBJECT_STORAGE=1 with a reachable configured MinIO")
    config = Settings()
    storage = MinioOriginalStorage(
        config.minio_url,
        config.minio_access_key.get_secret_value(),
        config.minio_secret_key.get_secret_value(),
        config.documents_bucket,
    )
    key = f"integration-fixtures/{uuid4()}"
    try:
        await storage.put(key, PDF, "application/pdf")

        def read() -> bytes:
            response = storage._client.get_object(Bucket=storage.bucket, Key=key)
            try:
                assert response["ContentType"] == "application/pdf"
                return response["Body"].read()
            finally:
                response["Body"].close()

        assert await asyncio.to_thread(read) == PDF
    finally:
        await storage.delete(key)
        await storage.close()


async def test_live_upload_api_persists_the_original_in_minio() -> None:
    from uuid import NAMESPACE_URL, uuid5

    url = os.getenv("TEST_DATABASE_URL")
    if os.getenv("TEST_OBJECT_STORAGE") != "1" or not url:
        pytest.skip("Set TEST_OBJECT_STORAGE=1 and TEST_DATABASE_URL for upload E2E")
    family_id, actor_id, key = uuid4(), uuid4(), uuid4()
    actor = Principal(actor_id, "e2e-document-" + uuid4().hex, UserRole.ADMIN, None)
    document_id = uuid5(NAMESPACE_URL, f"rag-upload:{actor_id}:{key}")
    object_key = f"originals/{family_id}/{document_id}"
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Synthetic evidence) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    content = buffer.getvalue()
    artifact_key = None
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(
                sa.insert(families).values(id=family_id, name="Synthetic upload E2E")
            )
            await SqlIdentityRepository(session).save_user(User(actor, "unused-no-login-fixture"))
        app = create_app(
            Settings(
                database_url=url,
                jwt_secret=SECRET,
                admin_username="test-admin",
                admin_password="synthetic-password",
            )
        )
        async with app.router.lifespan_context(app):
            store = app.state.original_storage
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        f"/documents?family_id={family_id}&filename=example.pdf&visibility=family",
                        headers={
                            "Authorization": "Bearer " + JwtTokens(SECRET).issue(actor),
                            "Content-Type": "application/pdf",
                            "Idempotency-Key": str(key),
                        },
                        content=content,
                    )
                    assert response.status_code == 201, response.text
                    assert response.json()["status"] == "uploaded"
                    assert response.json()["id"] == str(document_id)
                    auth = {"Authorization": "Bearer " + JwtTokens(SECRET).issue(actor)}
                    original = await client.get(f"/documents/{document_id}/download", headers=auth)
                    assert original.status_code == 200 and original.content == content
                    extracted = await client.post(f"/documents/{document_id}/extract", headers=auth)
                    assert extracted.status_code == 200, extracted.text
                    result = extracted.json()
                    artifact_key = f"extracted/{document_id}/{result['generation']}.json"
                    assert result["page_count"] == 2 and result["status"] == "extracted"
                    listing = await client.get(f"/documents?family_id={family_id}", headers=auth)
                    assert listing.json()[0]["title"] == "Synthetic evidence"
                    # Existing extractions backfill metadata without re-extracting the PDF.
                    async with app.state.db_session_factory() as session, session.begin():
                        await session.execute(
                            sa.update(documents)
                            .where(documents.c.id == document_id)
                            .values(title=None)
                        )
                    replay = await client.post(f"/documents/{document_id}/extract", headers=auth)
                    assert replay.json()["generation"] == result["generation"]
                    listing = await client.get(f"/documents?family_id={family_id}", headers=auth)
                    assert listing.json()[0]["title"] == "Synthetic evidence"
                    pages = await client.get(f"/documents/{document_id}/pages", headers=auth)
                    assert pages.status_code == 200, pages.text
                    assert pages.json()["pages"] == [
                        {"page_number": 1, "text": "Synthetic evidence"},
                        {"page_number": 2, "text": ""},
                    ]
                    assert (await client.get(f"/documents/{document_id}/pages")).status_code == 401

                def read_original() -> bytes:
                    result = store._client.get_object(Bucket=store.bucket, Key=object_key)
                    try:
                        return result["Body"].read()
                    finally:
                        result["Body"].close()

                assert await asyncio.to_thread(read_original) == content
            finally:
                await store.delete(object_key)
                if artifact_key:
                    await store.delete(artifact_key)
    finally:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(sa.delete(documents).where(documents.c.id == document_id))
            await session.execute(sa.delete(users).where(users.c.id == actor_id))
            await session.execute(sa.delete(families).where(families.c.id == family_id))
        await engine.dispose()
