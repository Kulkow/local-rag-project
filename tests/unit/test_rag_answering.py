from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.rag.application.answering import AnswerQuestion, RetrievedChunk, Scope
from app.modules.shared.domain.errors import ApplicationError


@pytest.fixture
def setup() -> tuple:
    repository, embeddings, vectors, chat = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    family_id, document_id, generation, chunk_id = uuid4(), uuid4(), uuid4(), uuid4()
    scope = Scope(document_id, generation, "synthetic-collection")
    repository.scopes.return_value = [scope]
    candidate = RetrievedChunk(
        chunk_id, document_id, generation, "guide.pdf", 1, "The retention period is 37 days.", 0.9
    )
    repository.keyword.return_value = [candidate]
    repository.read_candidates.return_value = [candidate]
    vectors.search.return_value = []
    embeddings.model, embeddings.dimensions = "synthetic", 3
    embeddings.identity.return_value = "digest"
    embeddings.embed.return_value = [[1.0, 0.0, 0.0]]
    chat.answer.return_value = {
        "answer": "Retention is 37 days [1].",
        "citations": [1],
        "insufficient_evidence": False,
    }
    return (
        AnswerQuestion(repository, embeddings, vectors, chat),
        repository,
        embeddings,
        vectors,
        chat,
        family_id,
    )


async def test_keyword_answer_has_server_mapped_citations(setup: tuple) -> None:
    use_case, repository, embeddings, _, chat, family_id = setup
    result = await use_case.execute(AsyncMock(), family_id, "Retention?", "keyword", 5, True)
    assert result.answer == "Retention is 37 days [1]." and not result.abstained
    assert result.citations == [1] and len(result.chunks) == 1
    embeddings.embed.assert_not_awaited()
    chat.answer.assert_awaited_once()
    repository.revalidate.assert_awaited()


async def test_empty_authorized_scope_never_calls_models_or_vectors(setup: tuple) -> None:
    use_case, repository, embeddings, vectors, chat, family_id = setup
    repository.scopes.return_value = []
    result = await use_case.execute(AsyncMock(), family_id, "Secret?", "vector", 5, True)
    assert result.abstained and result.reason == "no_evidence"
    embeddings.embed.assert_not_awaited()
    vectors.search.assert_not_awaited()
    chat.answer.assert_not_awaited()


async def test_acl_is_revalidated_before_generation(setup: tuple) -> None:
    use_case, repository, _, _, chat, family_id = setup
    repository.revalidate.side_effect = ApplicationError("unauthorized", "Revoked")
    with pytest.raises(ApplicationError):
        await use_case.execute(AsyncMock(), family_id, "Retention?", "keyword", 5, True)
    chat.answer.assert_not_awaited()


@pytest.mark.parametrize(
    "content",
    [
        {"answer": "Invented [9].", "citations": [9], "insufficient_evidence": False},
        {"answer": "Uncited answer", "citations": [], "insufficient_evidence": False},
        {"answer": "Answer [1]", "citations": [1], "insufficient_evidence": True},
        {"answer": "Wrong [2]", "citations": [1], "insufficient_evidence": False},
        {"answer": "Malformed", "citations": ["1"], "insufficient_evidence": False},
    ],
)
async def test_invalid_or_insufficient_model_output_abstains(setup: tuple, content: dict) -> None:
    use_case, _, _, _, chat, family_id = setup
    chat.answer.return_value = content
    result = await use_case.execute(AsyncMock(), family_id, "Retention?", "keyword", 5, True)
    assert result.abstained and result.citations == []


async def test_search_only_never_invokes_chat(setup: tuple) -> None:
    use_case, _, _, _, chat, family_id = setup
    result = await use_case.execute(AsyncMock(), family_id, "Retention?", "keyword", 5, False)
    assert len(result.chunks) == 1
    chat.answer.assert_not_awaited()


async def test_structured_citations_are_rendered_when_model_omits_inline_marks(
    setup: tuple,
) -> None:
    use_case, _, _, _, chat, family_id = setup
    chat.answer.return_value = {
        "answer": "Retention is 37 days.",
        "citations": [1],
        "insufficient_evidence": False,
    }
    result = await use_case.execute(AsyncMock(), family_id, "Retention?", "keyword", 5, True)
    assert not result.abstained and result.answer == "Retention is 37 days. [1]"
    assert result.citations == [1]


async def test_unknown_grouped_references_are_rejected(setup: tuple) -> None:
    use_case, _, _, _, chat, family_id = setup
    chat.answer.return_value = {
        "answer": "Retention is 37 days [1,9].",
        "citations": [1],
        "insufficient_evidence": False,
    }
    result = await use_case.execute(AsyncMock(), family_id, "Retention?", "keyword", 5, True)
    assert result.abstained and result.reason == "invalid_citations"
