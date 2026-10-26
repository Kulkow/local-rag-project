from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.domain.entities import Document, DocumentStatus, Visibility
from app.modules.documents.infrastructure.processing_repository import schedule_job
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError

metadata = sa.MetaData()
documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("family_id", sa.Uuid()),
    sa.Column("owner_id", sa.Uuid()),
    sa.Column("filename", sa.String(255)),
    sa.Column("content_type", sa.String(100)),
    sa.Column("size_bytes", sa.Integer()),
    sa.Column("checksum", sa.String(64)),
    sa.Column("object_key", sa.String(255)),
    sa.Column("visibility", sa.String(20)),
    sa.Column("status", sa.String(30)),
    sa.Column("error_code", sa.String(50)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


def to_document(row: sa.RowMapping) -> Document:
    return Document(
        row["id"],
        row["family_id"],
        row["owner_id"],
        row["filename"],
        row["content_type"],
        row["size_bytes"],
        row["checksum"],
        row["object_key"],
        Visibility(row["visibility"]),
        DocumentStatus(row["status"]),
        row["error_code"],
        row["created_at"],
    )


class SqlDocumentRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def reserve(self, document: Document) -> tuple[Document, bool]:
        async with self.factory() as session, session.begin():
            # Serialize content reservations across API processes, before any object I/O.
            await session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"document-content:{document.owner_id}:{document.checksum}"},
            )
            replay = await session.scalar(
                sa.select(documents.c.id).where(documents.c.id == document.id)
            )
            if replay is None:
                duplicate = await session.scalar(
                    sa.select(documents.c.id)
                    .where(
                        documents.c.owner_id == document.owner_id,
                        documents.c.checksum == document.checksum,
                    )
                    .limit(1)
                )
                if duplicate is not None:
                    raise ApplicationError(
                        "conflict",
                        "This document is already uploaded to your account. "
                        "For a failed upload, retry with the original upload key.",
                    )
            inserted = (
                await session.execute(
                    insert(documents)
                    .values(
                        id=document.id,
                        family_id=document.family_id,
                        owner_id=document.owner_id,
                        filename=document.filename,
                        content_type=document.content_type,
                        size_bytes=document.size_bytes,
                        checksum=document.checksum,
                        object_key=document.object_key,
                        visibility=document.visibility.value,
                        status=DocumentStatus.UPLOADING.value,
                    )
                    .on_conflict_do_nothing(index_elements=[documents.c.id])
                    .returning(documents.c.id)
                )
            ).scalar_one_or_none()
            row = (
                (
                    await session.execute(
                        sa.select(documents).where(documents.c.id == document.id).with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            existing = to_document(row)
            if inserted:
                return existing, True
            if (
                existing.family_id,
                existing.owner_id,
                existing.filename,
                existing.content_type,
                existing.checksum,
                existing.visibility,
            ) != (
                document.family_id,
                document.owner_id,
                document.filename,
                document.content_type,
                document.checksum,
                document.visibility,
            ):
                raise ApplicationError(
                    "conflict", "Upload key is already used for another file or access scope"
                )
            if existing.status == DocumentStatus.UPLOADED:
                return existing, False
            if existing.status == DocumentStatus.UPLOADING:
                raise ApplicationError(
                    "conflict", "Upload is already in progress; refresh document status"
                )
            retry = existing.retry_upload()
            await session.execute(
                sa.update(documents)
                .where(documents.c.id == existing.id)
                .values(status=retry.status.value, error_code=retry.error_code)
            )
            return retry, True

    async def complete(self, document: Document) -> Document:
        completed = document.complete_upload()
        async with self.factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        sa.update(documents)
                        .where(
                            documents.c.id == document.id,
                            documents.c.status == DocumentStatus.UPLOADING.value,
                        )
                        .values(status=completed.status.value, error_code=completed.error_code)
                        .returning(documents)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("conflict", "Upload is no longer in progress")
            result = to_document(row)
            if result.content_type == "application/pdf":
                await schedule_job(session, result.id, result.owner_id)
        return result

    async def fail(self, document: Document, error_code: str) -> None:
        failed = document.fail_upload(error_code)
        async with self.factory() as session, session.begin():
            await session.execute(
                sa.update(documents)
                .where(
                    documents.c.id == document.id,
                    documents.c.status == DocumentStatus.UPLOADING.value,
                )
                .values(status=failed.status.value, error_code=failed.error_code)
            )

    async def list(
        self, actor: Principal, family_id: UUID, offset: int, limit: int
    ) -> list[Document]:
        scope = (
            sa.true()
            if actor.is_admin
            else sa.or_(
                documents.c.owner_id == actor.id, documents.c.visibility == Visibility.FAMILY.value
            )
        )
        async with self.factory() as session:
            rows = (
                await session.execute(
                    sa.select(documents)
                    .where(documents.c.family_id == family_id, scope)
                    .order_by(documents.c.created_at.desc(), documents.c.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).mappings()
            return [to_document(row) for row in rows]
