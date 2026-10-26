"""Small async Qdrant REST adapter, using the existing httpx dependency."""

from uuid import UUID

import httpx

from app.modules.documents.application.indexing import IndexRecord
from app.modules.documents.domain.chunking import DocumentChunk
from app.modules.documents.domain.entities import Document
from app.modules.shared.domain.errors import ApplicationError


class QdrantIndex:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        allow_missing: bool = False,
    ) -> dict[str, object]:
        try:
            response = await self.client.request(method, self.base_url + path, json=payload)
            if allow_missing and response.status_code == 404:
                return {}
            response.raise_for_status()
            result: dict[str, object] = response.json()
            return result
        except (httpx.HTTPError, ValueError):
            raise ApplicationError("storage_unavailable", "Vector index request failed") from None

    async def ensure_collection(self, name: str, dimensions: int) -> None:
        path = f"/collections/{name}"
        existing = await self._request("GET", path, allow_missing=True)
        if not existing:
            await self._request(
                "PUT", path, {"vectors": {"size": dimensions, "distance": "Cosine"}}
            )
            existing = await self._request("GET", path)
        try:
            # Untyped JSON remains confined to this adapter.
            result = existing["result"]
            assert isinstance(result, dict)
            config = result["config"]["params"]["vectors"]
            if config["size"] != dimensions or config["distance"] != "Cosine":
                raise ApplicationError("invalid", "Qdrant collection vector configuration mismatch")
        except (KeyError, TypeError, AssertionError):
            raise ApplicationError("storage_unavailable", "Invalid collection response") from None
        for field in ("family_id", "document_id", "index_generation"):
            await self._request(
                "PUT", path + "/index?wait=true", {"field_name": field, "field_schema": "keyword"}
            )

    async def delete_document(self, name: str, family_id: UUID, document_id: UUID) -> None:
        await self._request(
            "POST",
            f"/collections/{name}/points/delete?wait=true",
            {
                "filter": {
                    "must": [
                        {"key": "family_id", "match": {"value": str(family_id)}},
                        {"key": "document_id", "match": {"value": str(document_id)}},
                    ]
                }
            },
            allow_missing=True,
        )

    async def upsert(
        self,
        record: IndexRecord,
        document: Document,
        chunks: tuple[DocumentChunk, ...],
        vectors: list[list[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ApplicationError("invalid", "Chunk/vector count mismatch")
        points = [
            {
                "id": str(chunk.id),
                "vector": vector,
                "payload": {
                    "chunk_id": str(chunk.id),
                    "document_id": str(document.id),
                    "family_id": str(document.family_id),
                    "owner_id": str(document.owner_id),
                    "visibility": document.visibility.value,
                    "index_generation": str(record.generation),
                    "page_number": chunk.page_number,
                    "ordinal": chunk.ordinal,
                    "embedding_digest": record.embedding_digest,
                },
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self._request(
            "PUT", f"/collections/{record.collection_name}/points?wait=true", {"points": points}
        )
