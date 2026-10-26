"""Read an authorized original without exposing an object-storage URL."""

import hashlib
from typing import Protocol
from uuid import UUID

from app.modules.documents.application.upload import FamilyAccess
from app.modules.documents.domain.entities import Document, DocumentStatus, MAX_FILE_BYTES
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError


class VisibleDocuments(Protocol):
    async def get_visible(self, actor: Principal, document_id: UUID) -> Document: ...


class OriginalReader(Protocol):
    async def get(self, key: str, max_bytes: int) -> bytes: ...


class DownloadDocument:
    def __init__(
        self, repository: VisibleDocuments, storage: OriginalReader, access: FamilyAccess
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.access = access

    async def execute(self, actor: Principal, document_id: UUID) -> tuple[Document, bytes]:
        document = await self.repository.get_visible(actor, document_id)
        await self.access.authorize(actor, document.family_id)
        if document.status != DocumentStatus.UPLOADED:
            raise ApplicationError("conflict", "Document upload is not complete")
        try:
            content = await self.storage.get(document.object_key, MAX_FILE_BYTES)
            if (
                len(content) != document.size_bytes
                or hashlib.sha256(content).hexdigest() != document.checksum
            ):
                raise ValueError("Original checksum mismatch")
        except Exception:
            raise ApplicationError(
                "storage_unavailable", "Document download is unavailable; retry later"
            ) from None
        return document, content
