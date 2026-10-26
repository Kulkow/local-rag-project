import asyncio
import hashlib
import json
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.documents.application.upload import FamilyAccess
from app.modules.documents.domain.entities import Document, DocumentStatus, MAX_FILE_BYTES
from app.modules.documents.domain.extraction import (
    ExtractedContent,
    Extraction,
    ExtractionFailure,
    ExtractionStatus,
    MAX_ARTIFACT_BYTES,
    PageText,
)
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError


class DocumentExtractor(Protocol):
    content_type: str
    name: str

    async def extract(self, content: bytes) -> ExtractedContent: ...


class ExtractorRegistry:
    def __init__(self, extractors: Sequence[DocumentExtractor]) -> None:
        self._extractors: dict[str, DocumentExtractor] = {}
        for extractor in extractors:
            if extractor.content_type in self._extractors:
                raise ValueError("Duplicate extractor for MIME type")
            self._extractors[extractor.content_type] = extractor

    def for_mime(self, content_type: str) -> DocumentExtractor:
        try:
            return self._extractors[content_type]
        except KeyError:
            raise ApplicationError(
                "unsupported_media", "Text extraction is not available for this document type"
            ) from None

    def content_types(self) -> list[str]:
        return list(self._extractors)


class ExtractionRepository(Protocol):
    async def get_visible(self, actor: Principal, document_id: UUID) -> Document: ...
    async def claim(self, document: Document) -> tuple[Extraction, bool]: ...
    async def complete(
        self, run: Extraction, page_count: int, character_count: int, artifact_key: str
    ) -> Extraction: ...
    async def fail(self, run: Extraction, code: str) -> None: ...
    async def get(self, document_id: UUID) -> Extraction | None: ...


class ExtractionStorage(Protocol):
    async def get(self, key: str, max_bytes: int) -> bytes: ...
    async def put(self, key: str, content: bytes, content_type: str) -> None: ...
    async def delete(self, key: str) -> None: ...


class ExtractDocument:
    def __init__(
        self,
        repository: ExtractionRepository,
        storage: ExtractionStorage,
        registry: ExtractorRegistry,
        access: FamilyAccess,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.registry = registry
        self.access = access

    async def execute(self, actor: Principal, document_id: UUID) -> Extraction:
        document = await self.repository.get_visible(actor, document_id)
        await self.access.authorize(actor, document.family_id, write=actor.id != document.owner_id)
        if document.status != DocumentStatus.UPLOADED:
            raise ApplicationError("conflict", "The original has not been uploaded successfully")
        extractor = self.registry.for_mime(document.content_type)
        run, claimed = await self.repository.claim(document)
        if not claimed:
            return run
        key = f"extracted/{document.id}/{run.generation}.json"
        try:
            async with asyncio.timeout(120):
                original = await self.storage.get(document.object_key, MAX_FILE_BYTES)
                if hashlib.sha256(original).hexdigest() != document.checksum:
                    raise ExtractionFailure("source_checksum_mismatch")
                content = await extractor.extract(original)
                payload = {
                    "schema_version": 1,
                    "document_id": str(document.id),
                    "generation": str(run.generation),
                    "source_checksum": document.checksum,
                    "extractor": extractor.name,
                    "pages": [
                        {"page_number": page.page_number, "text": page.text}
                        for page in content.pages
                    ],
                }
                artifact = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                if len(artifact) > MAX_ARTIFACT_BYTES:
                    raise ExtractionFailure("text_limit")
                await self.storage.put(key, artifact, "application/json")
                return await self.repository.complete(
                    run, len(content.pages), content.character_count, key
                )
        except (Exception, asyncio.CancelledError) as error:
            code = error.code if isinstance(error, ExtractionFailure) else "extraction_unavailable"
            try:
                await self.storage.delete(key)
            except Exception:
                code = "cleanup_required"
            try:
                await self.repository.fail(run, code)
            except Exception:
                pass
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, ApplicationError):
                raise
            if isinstance(error, ExtractionFailure):
                raise ApplicationError("invalid", f"Document extraction failed: {code}") from None
            raise ApplicationError(
                "storage_unavailable", "Text extraction could not finish; retry later"
            ) from None


class ReadExtractedPages:
    def __init__(
        self, repository: ExtractionRepository, storage: ExtractionStorage, access: FamilyAccess
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.access = access

    async def execute(
        self, actor: Principal, document_id: UUID, offset: int, limit: int
    ) -> tuple[Extraction, tuple[PageText, ...]]:
        document = await self.repository.get_visible(actor, document_id)
        await self.access.authorize(actor, document.family_id)
        run = await self.repository.get(document_id)
        if run is None or run.status != ExtractionStatus.EXTRACTED or not run.artifact_key:
            raise ApplicationError("conflict", "Document text has not been extracted yet")
        try:
            payload = json.loads(await self.storage.get(run.artifact_key, MAX_ARTIFACT_BYTES))
            if (
                payload["document_id"] != str(document.id)
                or payload["generation"] != str(run.generation)
                or payload["source_checksum"] != document.checksum
                or payload["schema_version"] != 1
            ):
                raise ValueError("Artifact provenance mismatch")
            content = ExtractedContent(
                tuple(PageText(page["page_number"], page["text"]) for page in payload["pages"])
            )
            if (
                len(content.pages) != run.page_count
                or content.character_count != run.character_count
            ):
                raise ValueError("Artifact metadata mismatch")
        except Exception:
            raise ApplicationError("storage_unavailable", "Extracted text is unavailable") from None
        return run, content.pages[offset : offset + limit]
