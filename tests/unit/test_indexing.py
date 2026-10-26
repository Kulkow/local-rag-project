from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.documents.application.indexing import IndexDocument
from app.modules.documents.domain.chunking import ChunkingConfig
from app.modules.documents.domain.entities import Document, DocumentStatus, Visibility
from app.modules.documents.domain.extraction import Extraction, ExtractionStatus, PageText
from app.modules.documents.infrastructure.embedding_provider import OllamaEmbeddings
from app.modules.documents.infrastructure.vector_index import QdrantIndex
from app.modules.shared.domain.errors import ApplicationError


@pytest.fixture
def setup() -> tuple:
    actor = AsyncMock()
    document = Document(
        uuid4(),
        uuid4(),
        uuid4(),
        "guide.pdf",
        "application/pdf",
        10,
        "a" * 64,
        "original",
        Visibility.PRIVATE,
        DocumentStatus.UPLOADED,
    )
    pages, repository, embeddings, vectors = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    pages.repository.get_visible.return_value = document
    pages.execute.return_value = (
        Extraction(document.id, uuid4(), ExtractionStatus.EXTRACTED),
        (PageText(1, "abcdefghij"),),
    )
    repository.get.return_value = None
    embeddings.model, embeddings.dimensions = "synthetic-model", 3
    embeddings.identity.return_value = "synthetic-digest"
    embeddings.embed.side_effect = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
    use_case = IndexDocument(
        pages, repository, embeddings, vectors, ChunkingConfig(6, 2), batch_size=1
    )
    return use_case, actor, document, pages, repository, embeddings, vectors


async def test_index_is_batched_idempotent_and_preserves_acl_metadata(setup: tuple) -> None:
    use_case, actor, document, pages, repository, embeddings, vectors = setup
    result = await use_case.execute(actor, document.id)
    assert result.status == "indexed" and result.chunk_count == 2
    assert embeddings.embed.await_count == 2
    vectors.delete_document.assert_awaited_once_with(
        result.collection_name, document.family_id, document.id
    )
    assert all(call.args[1] == document for call in vectors.upsert.await_args_list)
    pages.access.authorize.assert_awaited_once_with(actor, document.family_id, write=True)
    repository.get.return_value = result
    await use_case.execute(actor, document.id)
    assert embeddings.embed.await_count == 2
    repository.complete.assert_awaited_once()


async def test_authorization_precedes_model_and_vector_calls(setup: tuple) -> None:
    use_case, actor, document, pages, _, embeddings, vectors = setup
    pages.access.authorize.side_effect = ApplicationError("not_found", "Not accessible")
    with pytest.raises(ApplicationError):
        await use_case.execute(actor, document.id)
    embeddings.identity.assert_not_awaited()
    vectors.upsert.assert_not_awaited()
    pages.execute.assert_not_awaited()


async def test_failed_embedding_never_marks_index_ready(setup: tuple) -> None:
    use_case, actor, document, _, repository, embeddings, _ = setup
    embeddings.embed.side_effect = ApplicationError("storage_unavailable", "Unavailable")
    with pytest.raises(ApplicationError):
        await use_case.execute(actor, document.id)
    repository.fail.assert_awaited_once()
    repository.complete.assert_not_awaited()


async def test_changed_digest_reindexes_in_separate_collection(setup: tuple) -> None:
    use_case, actor, document, _, repository, embeddings, vectors = setup
    old = await use_case.execute(actor, document.id)
    repository.get.return_value = old
    embeddings.identity.return_value = "new-digest"
    new = await use_case.execute(actor, document.id)
    assert old.collection_name != new.collection_name
    assert old.fingerprint != new.fingerprint
    assert old.generation != new.generation
    assert any(
        call.args == (old.collection_name, document.family_id, document.id)
        for call in vectors.delete_document.await_args_list
    )


@pytest.mark.parametrize("raw", [[[1, 2]], [[0, 0, 0]], [[float("nan"), 1, 0]], []])
async def test_provider_rejects_invalid_vectors(raw: list) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=__import__("json").dumps({"embeddings": raw}))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaEmbeddings(client, "http://ollama", "synthetic", 3)
        with pytest.raises(ApplicationError):
            await provider.embed(["synthetic"])


async def test_qdrant_deletion_is_family_and_document_scoped() -> None:
    import json

    requests = []
    transport = httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200, json={"result": {}})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        family_id, document_id = uuid4(), uuid4()
        await QdrantIndex(client, "http://qdrant").delete_document(
            "synthetic", family_id, document_id
        )
    payload = json.loads(requests[0].content)
    assert payload["filter"]["must"] == [
        {"key": "family_id", "match": {"value": str(family_id)}},
        {"key": "document_id", "match": {"value": str(document_id)}},
    ]


async def test_explicit_rebuild_does_not_skip_ready_index(setup: tuple) -> None:
    use_case, actor, document, _, repository, embeddings, _ = setup
    result = await use_case.execute(actor, document.id)
    repository.get.return_value = result
    await use_case.execute(actor, document.id, force=True)
    assert embeddings.embed.await_count == 4


async def test_model_tag_change_during_job_prevents_ready_state(setup: tuple) -> None:
    use_case, actor, document, _, repository, embeddings, _ = setup
    embeddings.identity.side_effect = ["digest-before", "digest-after"]
    with pytest.raises(ApplicationError) as error:
        await use_case.execute(actor, document.id)
    assert error.value.code == "conflict"
    repository.complete.assert_not_awaited()
    repository.fail.assert_awaited_once()


async def test_member_owner_can_index_their_document(setup: tuple) -> None:
    from app.modules.identity.application.contracts import Principal, UserRole

    use_case, _, document, pages, _, _, _ = setup
    member = Principal(document.owner_id, "synthetic-member", UserRole.MEMBER, uuid4())
    result = await use_case.execute(member, document.id)
    assert result.status == "indexed"
    pages.access.authorize.assert_awaited_once_with(member, document.family_id, write=False)
