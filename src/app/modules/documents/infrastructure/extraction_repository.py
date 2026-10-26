from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.domain.entities import Document, Visibility
from app.modules.documents.domain.extraction import Extraction, ExtractionStatus
from app.modules.documents.infrastructure.repository import documents, to_document
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError

metadata = sa.MetaData()
extractions = sa.Table(
    "document_extractions",
    metadata,
    sa.Column("document_id", sa.Uuid(), primary_key=True),
    sa.Column("generation", sa.Uuid()),
    sa.Column("status", sa.String(20)),
    sa.Column("page_count", sa.Integer()),
    sa.Column("character_count", sa.Integer()),
    sa.Column("error_code", sa.String(50)),
    sa.Column("artifact_key", sa.String(255)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)


def to_extraction(row: sa.RowMapping) -> Extraction:
    return Extraction(
        row["document_id"],
        row["generation"],
        ExtractionStatus(row["status"]),
        row["page_count"],
        row["character_count"],
        row["error_code"],
        row["artifact_key"],
    )


class SqlExtractionRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def get_visible(self, actor: Principal, document_id: UUID) -> Document:
        scope = (
            sa.true()
            if actor.is_admin
            else sa.or_(
                documents.c.owner_id == actor.id, documents.c.visibility == Visibility.FAMILY.value
            )
        )
        async with self.factory() as session:
            row = (
                (
                    await session.execute(
                        sa.select(documents).where(documents.c.id == document_id, scope)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("not_found", "Document not found")
            return to_document(row)

    async def claim(self, document: Document) -> tuple[Extraction, bool]:
        generation = uuid4()
        lease = sa.func.now() + sa.text("interval '5 minutes'")
        async with self.factory() as session, session.begin():
            inserted = (
                await session.execute(
                    insert(extractions)
                    .values(
                        document_id=document.id,
                        generation=generation,
                        status="processing",
                        page_count=0,
                        character_count=0,
                        lease_until=lease,
                    )
                    .on_conflict_do_nothing(index_elements=[extractions.c.document_id])
                    .returning(extractions.c.document_id)
                )
            ).scalar_one_or_none()
            row = (
                (
                    await session.execute(
                        sa.select(
                            extractions,
                            (extractions.c.lease_until > sa.func.now()).label("live_lease"),
                        )
                        .where(extractions.c.document_id == document.id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if inserted:
                return to_extraction(row), True
            if row["status"] == "extracted":
                return to_extraction(row), False
            if row["status"] == "processing" and row["live_lease"]:
                raise ApplicationError("conflict", "Text extraction is already running")
            updated = (
                (
                    await session.execute(
                        sa.update(extractions)
                        .where(extractions.c.document_id == document.id)
                        .values(
                            generation=generation,
                            status="processing",
                            page_count=0,
                            character_count=0,
                            error_code=None,
                            artifact_key=None,
                            lease_until=lease,
                            updated_at=sa.func.now(),
                        )
                        .returning(extractions)
                    )
                )
                .mappings()
                .one()
            )
            return to_extraction(updated), True

    async def complete(
        self,
        run: Extraction,
        page_count: int,
        character_count: int,
        artifact_key: str,
        title: str | None = None,
    ) -> Extraction:
        completed = run.complete(page_count, character_count, artifact_key)
        async with self.factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        sa.update(extractions)
                        .where(
                            extractions.c.document_id == run.document_id,
                            extractions.c.generation == run.generation,
                            extractions.c.status == "processing",
                        )
                        .values(
                            status=completed.status.value,
                            page_count=completed.page_count,
                            character_count=completed.character_count,
                            artifact_key=completed.artifact_key,
                            error_code=completed.error_code,
                            updated_at=sa.func.now(),
                        )
                        .returning(extractions)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("conflict", "This extraction attempt has been superseded")
            await session.execute(
                sa.update(documents).where(documents.c.id == run.document_id).values(title=title)
            )
            result = to_extraction(row)
        return result

    async def set_title(self, run: Extraction, title: str | None) -> None:
        async with self.factory() as session, session.begin():
            current = await session.scalar(
                sa.select(extractions.c.document_id)
                .where(
                    extractions.c.document_id == run.document_id,
                    extractions.c.generation == run.generation,
                    extractions.c.status == "extracted",
                )
                .with_for_update()
            )
            if current is None:
                raise ApplicationError("conflict", "This extraction attempt has been superseded")
            await session.execute(
                sa.update(documents)
                .where(documents.c.id == run.document_id, documents.c.title.is_(None))
                .values(title=title)
            )

    async def fail(self, run: Extraction, code: str) -> None:
        failed = run.fail(code)
        async with self.factory() as session, session.begin():
            await session.execute(
                sa.update(extractions)
                .where(
                    extractions.c.document_id == run.document_id,
                    extractions.c.generation == run.generation,
                    extractions.c.status == "processing",
                )
                .values(
                    status=failed.status.value,
                    error_code=failed.error_code,
                    updated_at=sa.func.now(),
                )
            )

    async def get(self, document_id: UUID) -> Extraction | None:
        async with self.factory() as session:
            row = (
                (
                    await session.execute(
                        sa.select(extractions).where(extractions.c.document_id == document_id)
                    )
                )
                .mappings()
                .first()
            )
            return to_extraction(row) if row else None
