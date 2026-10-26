"""Authorized ingestion: normalized pages -> chunks -> embeddings -> persisted index."""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

from app.modules.documents.application.extraction import ReadExtractedPages
from app.modules.documents.application.upload import FamilyAccess
from app.modules.documents.domain.chunking import (
    CHUNKER_VERSION,
    ChunkingConfig,
    DocumentChunk,
    chunk_pages,
)
from app.modules.documents.domain.entities import Document
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError


@dataclass(frozen=True)
class IndexRecord:
    document_id: UUID
    generation: UUID
    fingerprint: str
    status: str
    collection_name: str
    embedding_model: str
    embedding_digest: str
    dimensions: int
    chunk_count: int = 0
    error_code: str | None = None


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    async def identity(self) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChunkIndex(Protocol):
    async def get(self, document_id: UUID) -> IndexRecord | None: ...
    async def start(
        self,
        record: IndexRecord,
        extraction_generation: UUID,
        checksum: str,
        config: ChunkingConfig,
    ) -> None: ...
    async def complete(self, record: IndexRecord, chunks: tuple[DocumentChunk, ...]) -> None: ...
    async def fail(self, record: IndexRecord) -> None: ...


class VectorIndex(Protocol):
    async def ensure_collection(self, name: str, dimensions: int) -> None: ...
    async def delete_document(self, name: str, family_id: UUID, document_id: UUID) -> None: ...
    async def upsert(
        self,
        record: IndexRecord,
        document: Document,
        chunks: tuple[DocumentChunk, ...],
        vectors: list[list[float]],
    ) -> None: ...


class IndexDocument:
    def __init__(
        self,
        pages: ReadExtractedPages,
        repository: ChunkIndex,
        embeddings: EmbeddingProvider,
        vectors: VectorIndex,
        config: ChunkingConfig,
        batch_size: int = 8,
        max_chunks: int = 2000,
    ) -> None:
        self.pages = pages
        self.repository = repository
        self.embeddings = embeddings
        self.vectors = vectors
        self.config = config
        self.batch_size = batch_size
        self.max_chunks = max_chunks
        if batch_size <= 0 or max_chunks <= 0:
            raise ValueError("Batch size and chunk limit must be positive")

    async def execute(
        self, actor: Principal, document_id: UUID, force: bool = False
    ) -> IndexRecord:
        document = await self.pages.repository.get_visible(actor, document_id)
        await self.pages.access.authorize(
            actor, document.family_id, write=actor.id != document.owner_id
        )
        extraction, pages = await self.pages.execute(actor, document_id, 0, 200)
        chunks = chunk_pages(document_id, document.checksum, pages, self.config)
        if not chunks or len(chunks) > self.max_chunks:
            raise ApplicationError("invalid", "Document exceeds indexing chunk limits")
        digest = await self.embeddings.identity()
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    document.checksum,
                    str(extraction.generation),
                    CHUNKER_VERSION,
                    self.config.size,
                    self.config.overlap,
                    self.embeddings.model,
                    digest,
                    self.embeddings.dimensions,
                ]
            ).encode()
        ).hexdigest()
        previous = await self.repository.get(document_id)
        if (
            not force
            and previous
            and previous.status == "indexed"
            and previous.fingerprint == fingerprint
        ):
            return previous
        model_hash = hashlib.sha256(
            f"{self.embeddings.model}:{digest}:{self.embeddings.dimensions}".encode()
        ).hexdigest()[:16]
        record = IndexRecord(
            document_id,
            uuid5(NAMESPACE_URL, f"index:{document_id}:{fingerprint}"),
            fingerprint,
            "indexing",
            f"rag_chunks_{model_hash}",
            self.embeddings.model,
            digest,
            self.embeddings.dimensions,
        )
        # Remove stale vectors before replacing their catalog location. Originals are untouched.
        if previous and previous.collection_name != record.collection_name:
            await self.vectors.delete_document(
                previous.collection_name, document.family_id, document_id
            )
        await self.repository.start(record, extraction.generation, document.checksum, self.config)
        try:
            await self.vectors.ensure_collection(record.collection_name, record.dimensions)
            await self.vectors.delete_document(
                record.collection_name, document.family_id, document_id
            )
            for offset in range(0, len(chunks), self.batch_size):
                batch = chunks[offset : offset + self.batch_size]
                vectors = await self.embeddings.embed([chunk.text for chunk in batch])
                await self.vectors.upsert(record, document, batch, vectors)
            if await self.embeddings.identity() != digest:
                raise ApplicationError("conflict", "Embedding model changed during indexing")
            await self.repository.complete(record, chunks)
        except Exception:
            # A failed index is never ready; partial vectors are reconciled on the next retry.
            await self.repository.fail(record)
            raise
        return IndexRecord(
            record.document_id,
            record.generation,
            record.fingerprint,
            "indexed",
            record.collection_name,
            record.embedding_model,
            record.embedding_digest,
            record.dimensions,
            len(chunks),
        )


class InspectIndex:
    def __init__(
        self, documents: ReadExtractedPages, indexes: ChunkIndex, access: FamilyAccess
    ) -> None:
        self.documents = documents
        self.indexes = indexes
        self.access = access

    async def execute(self, actor: Principal, document_id: UUID) -> IndexRecord:
        document = await self.documents.repository.get_visible(actor, document_id)
        await self.access.authorize(actor, document.family_id)
        record = await self.indexes.get(document_id)
        if record is None:
            raise ApplicationError("not_found", "Document is not indexed")
        return record
