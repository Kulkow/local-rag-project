"""Composition of the background extraction use case, one managed loop per task."""

import asyncio

import httpx
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.infrastructure.db.connection import create_engine
from app.modules.documents.application.extraction import (
    ExtractDocument,
    ExtractorRegistry,
    ReadExtractedPages,
)
from app.modules.documents.application.indexing import IndexDocument
from app.modules.documents.domain.chunking import ChunkingConfig
from app.modules.documents.infrastructure.chunk_repository import SqlChunkIndex
from app.modules.documents.infrastructure.embedding_provider import OllamaEmbeddings
from app.modules.documents.infrastructure.vector_index import QdrantIndex
from app.modules.documents.application.processing import ProcessNextDocument
from app.modules.documents.domain.processing import ProcessingJob
from app.modules.documents.infrastructure.extraction_repository import SqlExtractionRepository
from app.modules.documents.infrastructure.family_access import ScopedFamilyAccess
from app.modules.documents.infrastructure.object_storage import MinioOriginalStorage
from app.modules.documents.infrastructure.pdf_extractor import PdfExtractor
from app.modules.documents.infrastructure.processing_repository import SqlProcessingRepository
from app.modules.identity.infrastructure.repository import SqlIdentityRepository
from app.modules.shared.domain.errors import ApplicationError

# Also prevents parallel queue consumption if a second worker is accidentally started.
PROCESSING_LOCK = 739104
HEARTBEAT_KEY = "rag:processing:heartbeat"


class ExtractQueuedDocument:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        storage: MinioOriginalStorage,
        indexer: IndexDocument,
    ) -> None:
        self.factory = factory
        self.indexer = indexer
        self.use_case = ExtractDocument(
            SqlExtractionRepository(factory),
            storage,
            ExtractorRegistry([PdfExtractor()]),
            ScopedFamilyAccess(factory),
        )

    async def execute(self, job: ProcessingJob) -> None:
        async with self.factory() as session:
            actor = await SqlIdentityRepository(session).active_principal(job.requested_by)
        if actor is None:
            raise ApplicationError("forbidden", "Processing requester is inactive")
        # Both family authorization and document visibility are rechecked at execution time.
        async with asyncio.timeout(480):
            await self.use_case.execute(actor, job.document_id)
            await self.indexer.execute(actor, job.document_id, force=job.reindex)


async def process_tick(config: Settings) -> None:
    engine = create_engine(config.database_url.get_secret_value())
    storage: MinioOriginalStorage | None = None
    try:
        async with Redis.from_url(
            config.redis_url, socket_timeout=3, socket_connect_timeout=3
        ) as redis:
            await redis.set(HEARTBEAT_KEY, "1", ex=600)
        async with engine.begin() as guard:
            locked = await guard.scalar(
                sa.text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": PROCESSING_LOCK}
            )
            if not locked:
                return
            storage = await asyncio.to_thread(
                MinioOriginalStorage,
                config.minio_url,
                config.minio_access_key.get_secret_value(),
                config.minio_secret_key.get_secret_value(),
                config.documents_bucket,
            )
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60, connect=5), follow_redirects=False
            ) as client:
                indexer = IndexDocument(
                    ReadExtractedPages(
                        SqlExtractionRepository(factory), storage, ScopedFamilyAccess(factory)
                    ),
                    SqlChunkIndex(factory),
                    OllamaEmbeddings(
                        client,
                        config.ollama_url,
                        config.embedding_model,
                        config.embedding_dimensions,
                    ),
                    QdrantIndex(client, config.qdrant_url),
                    ChunkingConfig(config.chunk_size, config.chunk_overlap),
                    config.embedding_batch_size,
                    config.max_document_chunks,
                )
                await ProcessNextDocument(
                    SqlProcessingRepository(factory),
                    ExtractQueuedDocument(factory, storage, indexer),
                ).execute()
    finally:
        try:
            if storage is not None:
                await storage.close()
        finally:
            await engine.dispose()
