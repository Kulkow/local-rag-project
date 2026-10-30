from unittest.mock import ANY, AsyncMock
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


async def test_keyword_metrics_include_stages_without_request_content(setup: tuple) -> None:
    from app.observability.rag_metrics import PrometheusRagObserver

    use_case, _, _, _, _, family_id = setup
    observer = PrometheusRagObserver()
    use_case.observer = observer
    result = await use_case.execute(AsyncMock(), family_id, "PRIVATE question", "keyword", 5, True)
    for stage in (
        "scope",
        "keyword_search",
        "context",
        "retrieval",
        "acl_revalidation",
        "generation",
        "citation_validation",
    ):
        assert result.timings[f"{stage}_ms"] >= 0
    assert (
        observer.registry.get_sample_value(
            "rag_requests_total", {"mode": "keyword", "operation": "ask", "outcome": "answered"}
        )
        == 1
    )
    labels = {
        "mode": "keyword",
        "operation": "ask",
        "stage": "acl_revalidation",
        "outcome": "success",
    }
    assert observer.registry.get_sample_value("rag_stage_duration_seconds_count", labels) == 2
    text = observer.render().decode()
    assert "PRIVATE" not in text and str(family_id) not in text and "guide.pdf" not in text
    assert "query_embedding" not in text and "vector_search" not in text


async def test_vector_search_only_records_only_executed_stages(setup: tuple) -> None:
    from dataclasses import replace
    from app.observability.rag_metrics import PrometheusRagObserver

    use_case, repository, _, _, chat, family_id = setup
    repository.scopes.return_value = [
        replace(
            repository.scopes.return_value[0],
            embedding_model="synthetic",
            embedding_digest="digest",
            dimensions=3,
        )
    ]
    observer = PrometheusRagObserver()
    use_case.observer = observer
    result = await use_case.execute(AsyncMock(), family_id, "Retention?", "vector", 5, False)
    assert {
        "query_embedding_ms",
        "vector_search_ms",
        "candidate_read_ms",
        "embedding_identity_ms",
    } <= result.timings.keys()
    assert "generation_ms" not in result.timings and "keyword_search_ms" not in result.timings
    assert (
        observer.registry.get_sample_value(
            "rag_requests_total",
            {"mode": "vector", "operation": "search", "outcome": "search_only"},
        )
        == 1
    )
    chat.answer.assert_not_awaited()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_metrics_record_failure_or_cancellation_without_hiding_it(
    setup: tuple, cancelled: bool
) -> None:
    import asyncio
    from app.observability.rag_metrics import PrometheusRagObserver

    use_case, _, _, _, chat, family_id = setup
    observer = PrometheusRagObserver()
    use_case.observer = observer
    chat.answer.side_effect = (
        asyncio.CancelledError() if cancelled else OSError("private provider failure")
    )
    with pytest.raises(asyncio.CancelledError if cancelled else OSError):
        await use_case.execute(AsyncMock(), family_id, "secret", "keyword", 5, True)
    outcome = "cancelled" if cancelled else "error"
    assert (
        observer.registry.get_sample_value(
            "rag_requests_total", {"mode": "keyword", "operation": "ask", "outcome": outcome}
        )
        == 1
    )
    assert (
        observer.registry.get_sample_value(
            "rag_stage_duration_seconds_count",
            {"mode": "keyword", "operation": "ask", "stage": "generation", "outcome": outcome},
        )
        == 1
    )
    assert "private provider" not in observer.render().decode()


async def test_abstention_explains_missing_indexes_vs_missing_matches(setup: tuple) -> None:
    use_case, repository, _, _, _, family_id = setup
    repository.keyword.return_value = []
    empty_search = await use_case.execute(AsyncMock(), family_id, "question", "keyword", 5, True)
    assert "не нашёл подходящих фрагментов" in empty_search.answer
    repository.scopes.return_value = []
    empty_scope = await use_case.execute(AsyncMock(), family_id, "question", "keyword", 5, True)
    assert "нет доступных вам документов с готовым индексом" in empty_scope.answer


async def test_invalid_model_output_describes_fields_without_echoing_content(setup: tuple) -> None:
    use_case, _, _, _, chat, family_id = setup
    chat.answer.return_value = {"answer": "PRIVATE MODEL OUTPUT", "citations": [99]}
    result = await use_case.execute(AsyncMock(), family_id, "question", "keyword", 5, True)
    assert result.reason == "invalid_model_output"
    assert "несуществующие номера" in result.answer
    assert "insufficient_evidence" in result.answer
    assert "PRIVATE MODEL OUTPUT" not in result.answer


@pytest.mark.parametrize(
    "reason,phrase",
    [
        ("incompatible_index", "несовместим"),
        ("model_changed", "изменилась во время поиска"),
        ("insufficient_evidence", "модель сообщила"),
        ("invalid_model_output", "не прошёл проверку формата"),
        ("invalid_citations", "не указанные в её списке цитат"),
    ],
)
async def test_abstention_reasons_have_actionable_descriptions(
    setup: tuple, reason: str, phrase: str
) -> None:
    from dataclasses import replace

    use_case, repository, embeddings, _, chat, family_id = setup
    mode = "keyword"
    if reason in ("incompatible_index", "model_changed"):
        mode = "vector"
        if reason == "model_changed":
            repository.scopes.return_value = [
                replace(
                    repository.scopes.return_value[0],
                    embedding_model="synthetic",
                    embedding_digest="digest",
                    dimensions=3,
                )
            ]
            embeddings.identity.side_effect = ["digest", "changed"]
    elif reason == "insufficient_evidence":
        chat.answer.return_value = {"answer": "", "citations": [], "insufficient_evidence": True}
    elif reason == "invalid_model_output":
        chat.answer.return_value = {}
    else:
        chat.answer.return_value = {
            "answer": "Incorrect [9]",
            "citations": [1],
            "insufficient_evidence": False,
        }
    result = await use_case.execute(AsyncMock(), family_id, "Question", mode, 5, True)
    assert result.reason == reason and result.abstained
    assert phrase in result.answer


async def test_empty_search_only_also_explains_the_reason(setup: tuple) -> None:
    use_case, repository, _, _, chat, family_id = setup
    repository.scopes.return_value = []
    result = await use_case.execute(AsyncMock(), family_id, "Question", "keyword", 5, False)
    assert "нет доступных вам документов с готовым индексом" in result.answer
    chat.answer.assert_not_awaited()


async def test_rewrite_retries_keyword_once_and_answers_original_question(setup: tuple) -> None:
    use_case, repository, _, _, chat, family_id = setup
    chunk = repository.keyword.return_value[0]
    repository.keyword.side_effect = [[], [chunk]]
    rewriter = AsyncMock()
    rewriter.rewrite.return_value = "retention period"
    use_case.rewriter = rewriter
    actor = AsyncMock()
    result = await use_case.execute(
        actor, family_id, "How long are files kept?", "keyword", 5, True
    )
    assert not result.abstained
    assert [call.args[2] for call in repository.keyword.await_args_list] == [
        "How long are files kept?",
        "retention period",
    ]
    assert all(call.args[:2] == (actor, family_id) for call in repository.keyword.await_args_list)
    assert repository.scopes.await_count == 2
    rewriter.rewrite.assert_awaited_once_with("How long are files kept?", usage=ANY)
    assert chat.answer.await_args.args[0] == "How long are files kept?"
    assert "query_rewriting_ms" in result.timings and "query_retry_ms" in result.timings


@pytest.mark.parametrize("rewritten", [None, "", "Original?", "x" * 201, "query\nnext"])
async def test_invalid_unchanged_rewrite_is_not_retried(setup: tuple, rewritten: object) -> None:
    use_case, repository, _, _, chat, family_id = setup
    repository.keyword.return_value = []
    use_case.rewriter = AsyncMock()
    use_case.rewriter.rewrite.return_value = rewritten
    result = await use_case.execute(AsyncMock(), family_id, "Original?", "keyword", 5, True)
    assert result.abstained and result.reason == "no_evidence"
    assert repository.keyword.await_count == 1
    chat.answer.assert_not_awaited()


async def test_rewrite_empty_retry_stops_after_two_searches(setup: tuple) -> None:
    use_case, repository, _, _, chat, family_id = setup
    repository.keyword.return_value = []
    use_case.rewriter = AsyncMock()
    use_case.rewriter.rewrite.return_value = "different query"
    result = await use_case.execute(AsyncMock(), family_id, "Original?", "keyword", 5, True)
    assert result.abstained and repository.keyword.await_count == 2
    use_case.rewriter.rewrite.assert_awaited_once()
    chat.answer.assert_not_awaited()


@pytest.mark.parametrize("scenario", ["found", "no_scope", "search_only", "incompatible"])
async def test_rewrite_is_skipped_without_eligible_empty_answer_search(
    setup: tuple, scenario: str
) -> None:
    use_case, repository, _, _, _, family_id = setup
    rewriter = AsyncMock()
    use_case.rewriter = rewriter
    if scenario == "no_scope":
        repository.scopes.return_value = []
    if scenario == "search_only":
        repository.keyword.return_value = []
    await use_case.execute(
        AsyncMock(),
        family_id,
        "Original?",
        "vector" if scenario == "incompatible" else "keyword",
        5,
        scenario != "search_only",
    )
    rewriter.rewrite.assert_not_awaited()


async def test_rewrite_provider_failure_keeps_safe_abstention(setup: tuple) -> None:
    use_case, repository, _, _, chat, family_id = setup
    repository.keyword.return_value = []
    use_case.rewriter = AsyncMock()
    use_case.rewriter.rewrite.side_effect = ApplicationError("storage_unavailable", "Synthetic")
    result = await use_case.execute(AsyncMock(), family_id, "Original?", "keyword", 5, True)
    assert result.abstained and repository.keyword.await_count == 1
    chat.answer.assert_not_awaited()


async def test_rewrite_revoked_scope_prevents_retry_evidence(setup: tuple) -> None:
    use_case, repository, _, _, chat, family_id = setup
    repository.scopes.side_effect = [repository.scopes.return_value, []]
    repository.keyword.return_value = []
    use_case.rewriter = AsyncMock()
    use_case.rewriter.rewrite.return_value = "different query"
    result = await use_case.execute(AsyncMock(), family_id, "Original?", "keyword", 5, True)
    assert result.abstained and repository.keyword.await_count == 1
    chat.answer.assert_not_awaited()


async def test_rewrite_vector_retry_preserves_eligible_scope(setup: tuple) -> None:
    use_case, repository, embeddings, vectors, _, family_id = setup
    from dataclasses import replace

    scope = replace(
        repository.scopes.return_value[0],
        embedding_model="synthetic",
        embedding_digest="digest",
        dimensions=3,
    )
    repository.scopes.return_value = [scope]
    chunk = repository.read_candidates.return_value[0]
    repository.read_candidates.side_effect = [[], [chunk]]
    use_case.rewriter = AsyncMock()
    use_case.rewriter.rewrite.return_value = "retention period"
    result = await use_case.execute(AsyncMock(), family_id, "Original?", "vector", 5, True)
    assert not result.abstained
    assert [call.args[0] for call in embeddings.embed.await_args_list] == [
        ["Original?"],
        ["retention period"],
    ]
    assert vectors.search.await_count == 2
    assert all(call.args[1] == [scope] for call in vectors.search.await_args_list)


async def test_rewrite_deadline_and_cancellation(setup: tuple) -> None:
    import asyncio

    use_case, repository, _, _, _, family_id = setup
    repository.keyword.return_value = []
    use_case.rewriter = AsyncMock()

    async def delayed(question: str, **kwargs: object) -> str:
        await asyncio.sleep(1)
        return "retention"

    use_case.rewriter.rewrite.side_effect = delayed
    use_case.rewrite_timeout = 0.001
    result = await use_case.execute(AsyncMock(), family_id, "Original?", "keyword", 5, True)
    assert result.abstained and repository.keyword.await_count == 1
    use_case.rewriter.rewrite.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await use_case.execute(AsyncMock(), family_id, "Original?", "keyword", 5, True)


async def test_hybrid_rrf_uses_rank_positions_not_raw_scores(setup: tuple) -> None:
    from dataclasses import replace

    use_case, repository, embeddings, _, _, family_id = setup
    a = repository.keyword.return_value[0]
    b = replace(a, chunk_id=uuid4(), score=0.001)
    repository.keyword.return_value = [a, b]
    repository.read_candidates.return_value = [b]
    repository.scopes.return_value = [
        replace(
            repository.scopes.return_value[0],
            embedding_model=embeddings.model,
            embedding_digest="digest",
            dimensions=3,
        )
    ]
    result = await use_case.execute(AsyncMock(), family_id, "retention", "hybrid", 2, False)
    assert [chunk.chunk_id for chunk in result.chunks] == [b.chunk_id, a.chunk_id]
    assert result.chunks[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert repository.keyword.await_args.args[-1] == 6
    assert "rrf_ms" in result.timings and not result.reranked


async def test_hybrid_reranker_reorders_only_authorized_candidates(setup: tuple) -> None:
    from dataclasses import replace

    use_case, repository, _, _, chat, family_id = setup
    a = repository.keyword.return_value[0]
    b = replace(a, chunk_id=uuid4(), text="Other evidence")
    repository.keyword.return_value = [a, b]
    # Incompatible embeddings leave the independent keyword path available.
    reranker = AsyncMock()
    reranker.rank.return_value = [1, 0]
    use_case.reranker = reranker
    result = await use_case.execute(AsyncMock(), family_id, "retention", "hybrid", 1, True)
    assert result.reranked and result.chunks[0].chunk_id == b.chunk_id
    reranker.rank.assert_awaited_once_with("retention", [a.text, b.text], usage=ANY)
    assert "reranking_ms" in result.timings
    assert chat.answer.await_args.args[1] == result.chunks


@pytest.mark.parametrize("order", [None, [0, 0], [2, 1], [True, 0]])
async def test_bad_reranker_output_keeps_rrf_order(setup: tuple, order: object) -> None:
    from dataclasses import replace

    use_case, repository, _, _, _, family_id = setup
    a = repository.keyword.return_value[0]
    repository.keyword.return_value = [a, replace(a, chunk_id=uuid4())]
    use_case.reranker = AsyncMock()
    use_case.reranker.rank.return_value = order
    result = await use_case.execute(AsyncMock(), family_id, "retention", "hybrid", 2, True)
    assert not result.reranked and result.chunks[0].chunk_id == a.chunk_id


async def test_reranker_failure_falls_back_but_acl_failure_propagates(setup: tuple) -> None:
    from dataclasses import replace

    use_case, repository, _, _, chat, family_id = setup
    a = repository.keyword.return_value[0]
    repository.keyword.return_value = [a, replace(a, chunk_id=uuid4())]
    use_case.reranker = AsyncMock()
    use_case.reranker.rank.side_effect = ApplicationError("storage_unavailable", "Synthetic")
    result = await use_case.execute(AsyncMock(), family_id, "retention", "hybrid", 2, True)
    assert not result.reranked and not result.abstained
    use_case.reranker.reset_mock()
    chat.reset_mock()
    repository.revalidate.side_effect = ApplicationError("conflict", "Evidence revoked")
    with pytest.raises(ApplicationError):
        await use_case.execute(AsyncMock(), family_id, "retention", "hybrid", 2, True)
    use_case.reranker.rank.assert_not_awaited()
    chat.answer.assert_not_awaited()


async def test_search_only_skips_llm_reranker(setup: tuple) -> None:
    from dataclasses import replace

    use_case, repository, _, _, _, family_id = setup
    a = repository.keyword.return_value[0]
    repository.keyword.return_value = [a, replace(a, chunk_id=uuid4())]
    use_case.reranker = AsyncMock()
    await use_case.execute(AsyncMock(), family_id, "retention", "hybrid", 2, False)
    use_case.reranker.rank.assert_not_awaited()
