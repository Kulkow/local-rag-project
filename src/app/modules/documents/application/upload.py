import asyncio
from typing import Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

from app.modules.documents.domain.entities import Document, Visibility, validate_file
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError


class DocumentRepository(Protocol):
    async def reserve(self, document: Document) -> tuple[Document, bool]:
        """Atomically reject same-owner checksum duplicates; allow same-key retries."""
        ...

    async def complete(self, document: Document) -> Document: ...
    async def fail(self, document: Document, error_code: str) -> None: ...
    async def list(
        self, actor: Principal, family_id: UUID, offset: int, limit: int
    ) -> list[Document]: ...


class OriginalStorage(Protocol):
    async def put(self, key: str, content: bytes, content_type: str) -> None: ...
    async def delete(self, key: str) -> None: ...


class FamilyAccess(Protocol):
    async def authorize(self, actor: Principal, family_id: UUID, write: bool = False) -> object: ...


class UploadDocument:
    def __init__(
        self, repository: DocumentRepository, storage: OriginalStorage, access: FamilyAccess
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.access = access

    async def execute(
        self,
        actor: Principal,
        family_id: UUID,
        filename: str,
        content_type: str,
        content: bytes,
        idempotency_key: UUID,
        visibility: Visibility,
    ) -> Document:
        await self.access.authorize(actor, family_id, write=False)
        mime, checksum = await asyncio.to_thread(validate_file, filename, content_type, content)
        document_id = uuid5(NAMESPACE_URL, f"rag-upload:{actor.id}:{idempotency_key}")
        document = Document(
            document_id,
            family_id,
            actor.id,
            filename,
            mime,
            len(content),
            checksum,
            f"originals/{family_id}/{document_id}",
            visibility,
        )
        document, should_upload = await self.repository.reserve(document)
        if not should_upload:
            return document
        try:
            await self.storage.put(document.object_key, content, mime)
            return await self.repository.complete(document)
        except (Exception, asyncio.CancelledError) as error:
            code = "storage_unavailable"
            try:
                await self.storage.delete(document.object_key)
            except Exception:
                code = "cleanup_required"
            try:
                await self.repository.fail(document, code)
            except Exception:
                # The durable uploading row remains available for operator reconciliation.
                pass
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ApplicationError(
                "storage_unavailable",
                "Upload failed. Retry the same file with the same upload key.",
            ) from error


class ListDocuments:
    def __init__(self, repository: DocumentRepository, access: FamilyAccess) -> None:
        self.repository = repository
        self.access = access

    async def execute(
        self, actor: Principal, family_id: UUID, offset: int, limit: int
    ) -> list[Document]:
        await self.access.authorize(actor, family_id)
        return await self.repository.list(actor, family_id, offset, limit)
