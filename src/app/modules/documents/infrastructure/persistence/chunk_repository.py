from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.documents.application.indexing import IndexRecord
from app.modules.documents.domain.chunking import CHUNKER_VERSION, ChunkingConfig, DocumentChunk
from app.modules.shared.domain.errors import ApplicationError

metadata = sa.MetaData()
indexes = sa.Table(
    "document_indexes",
    metadata,
    sa.Column("document_id", sa.Uuid(), primary_key=True),
    sa.Column("generation", sa.Uuid()),
    sa.Column("fingerprint", sa.String(64)),
    sa.Column("source_checksum", sa.String(64)),
    sa.Column("extraction_generation", sa.Uuid()),
    sa.Column("status", sa.String(20)),
    sa.Column("collection_name", sa.String(100)),
    sa.Column("embedding_model", sa.String(200)),
    sa.Column("embedding_digest", sa.String(128)),
    sa.Column("dimensions", sa.Integer()),
    sa.Column("chunker_version", sa.String(50)),
    sa.Column("chunk_size", sa.Integer()),
    sa.Column("chunk_overlap", sa.Integer()),
    sa.Column("chunk_count", sa.Integer()),
    sa.Column("error_code", sa.String(50)),
    sa.Column("indexed_at", sa.DateTime(timezone=True)),
)
chunks_table = sa.Table(
    "document_chunks",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("document_id", sa.Uuid()),
    sa.Column("index_generation", sa.Uuid()),
    sa.Column("ordinal", sa.Integer()),
    sa.Column("page_number", sa.Integer()),
    sa.Column("start_offset", sa.Integer()),
    sa.Column("end_offset", sa.Integer()),
    sa.Column("text", sa.Text()),
)


class SqlChunkIndex:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def get(self, document_id: UUID) -> IndexRecord | None:
        async with self.factory() as session:
            row = (
                (
                    await session.execute(
                        sa.select(indexes).where(indexes.c.document_id == document_id)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return IndexRecord(
                row["document_id"],
                row["generation"],
                row["fingerprint"],
                row["status"],
                row["collection_name"],
                row["embedding_model"],
                row["embedding_digest"],
                row["dimensions"],
                row["chunk_count"],
                row["error_code"],
            )

    async def start(
        self,
        record: IndexRecord,
        extraction_generation: UUID,
        checksum: str,
        config: ChunkingConfig,
    ) -> None:
        values = dict(
            document_id=record.document_id,
            generation=record.generation,
            fingerprint=record.fingerprint,
            source_checksum=checksum,
            extraction_generation=extraction_generation,
            status="indexing",
            collection_name=record.collection_name,
            embedding_model=record.embedding_model,
            embedding_digest=record.embedding_digest,
            dimensions=record.dimensions,
            chunker_version=CHUNKER_VERSION,
            chunk_size=config.size,
            chunk_overlap=config.overlap,
            chunk_count=0,
            error_code=None,
            indexed_at=None,
        )
        async with self.factory() as session, session.begin():
            await session.execute(
                insert(indexes)
                .values(**values)
                .on_conflict_do_update(index_elements=[indexes.c.document_id], set_=values)
            )

    async def complete(self, record: IndexRecord, chunks: tuple[DocumentChunk, ...]) -> None:
        async with self.factory() as session, session.begin():
            updated = (
                await session.execute(
                    sa.update(indexes)
                    .where(
                        indexes.c.document_id == record.document_id,
                        indexes.c.generation == record.generation,
                        indexes.c.status == "indexing",
                    )
                    .values(
                        status="indexed",
                        chunk_count=len(chunks),
                        indexed_at=sa.func.now(),
                        error_code=None,
                    )
                    .returning(indexes.c.document_id)
                )
            ).scalar_one_or_none()
            if updated is None:
                raise ApplicationError("conflict", "Index generation has changed")
            await session.execute(
                sa.delete(chunks_table).where(chunks_table.c.document_id == record.document_id)
            )
            await session.execute(
                sa.insert(chunks_table),
                [
                    dict(
                        id=chunk.id,
                        document_id=chunk.document_id,
                        index_generation=record.generation,
                        ordinal=chunk.ordinal,
                        page_number=chunk.page_number,
                        start_offset=chunk.start_offset,
                        end_offset=chunk.end_offset,
                        text=chunk.text,
                    )
                    for chunk in chunks
                ],
            )

    async def fail(self, record: IndexRecord) -> None:
        async with self.factory() as session, session.begin():
            await session.execute(
                sa.update(indexes)
                .where(
                    indexes.c.document_id == record.document_id,
                    indexes.c.generation == record.generation,
                    indexes.c.status == "indexing",
                )
                .values(status="failed", error_code="indexing_failed")
            )
