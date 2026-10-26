"""RAG orchestration with pre-retrieval ACL scope and validated citation mapping."""

import asyncio
import re
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Protocol
from uuid import UUID

from app.modules.documents.application.indexing import EmbeddingProvider
from app.modules.identity.application.contracts import Principal
from app.modules.shared.domain.errors import ApplicationError
from app.modules.rag.domain.ranking import reciprocal_rank_fusion
from app.modules.rag.application.reranking import Reranker, valid_order
from app.modules.rag.application.rewriting import QueryRewriter, validated_rewrite

from app.modules.rag.application.telemetry import (
    Mode as Mode,
    RagMeasurements,
    RagObserver,
    NullRagObserver,
    RunOutcome,
    Operation,
)

ABSTENTION = "Недостаточно подтверждённых данных в доступных документах."
ABSTENTION_DETAILS = {
    "no_evidence": "Поиск не нашёл подходящих фрагментов в доступных проиндексированных документах. Уточните вопрос или попробуйте другой режим поиска.",
    "incompatible_index": "Индекс доступных документов несовместим с текущей моделью эмбеддингов: отличаются модель, её версия или размерность. Переиндексируйте документы либо верните прежнюю модель.",
    "model_changed": "Модель эмбеддингов изменилась во время поиска. Полученные фрагменты отброшены. Повторите запрос; если ошибка повторяется, проверьте настройки модели и переиндексацию.",
    "insufficient_evidence": "Фрагменты найдены, но модель сообщила, что их недостаточно для подтверждённого ответа. Откройте источники, уточните вопрос или добавьте документ с нужными сведениями.",
    "invalid_model_output": "Модель вернула ответ, который не прошёл проверку формата. Ответ не показан, чтобы не выдавать неподтверждённые сведения.",
    "invalid_citations": "Модель сослалась в тексте на источники, не указанные в её списке цитат. Ответ отклонён. Повторите запрос или проверьте найденные фрагменты.",
}


def model_output_issues(output: dict[str, object], count: int) -> list[str]:
    """Describe schema violations without exposing the model's untrusted content."""
    issues: list[str] = []
    answer, citations = output.get("answer"), output.get("citations")
    if not isinstance(answer, str) or not answer.strip():
        issues.append("Поле answer отсутствует, пустое или не является строкой.")
    elif len(answer.strip()) > 6000:
        issues.append("Поле answer превышает лимит 6000 символов.")
    if not isinstance(citations, list) or not citations:
        issues.append("Поле citations должно содержать непустой список ссылок на источники.")
    elif not all(type(index) is int and 1 <= index <= count for index in citations):
        issues.append("Список citations содержит нецелые или несуществующие номера источников.")
    if output.get("insufficient_evidence") is not False:
        issues.append(
            "Поле insufficient_evidence должно быть boolean false для подтверждённого ответа."
        )
    return issues


@dataclass(frozen=True)
class Scope:
    document_id: UUID
    generation: UUID
    collection: str
    embedding_model: str = ""
    embedding_digest: str = ""
    dimensions: int = 0


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    document_id: UUID
    generation: UUID
    score: float


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    generation: UUID
    filename: str
    page_number: int
    text: str
    score: float


@dataclass
class RagResult:
    answer: str = ABSTENTION
    abstained: bool = True
    reason: str | None = "no_evidence"
    citations: list[int] = field(default_factory=list)
    chunks: list[RetrievedChunk] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    reranked: bool = False


class EvidenceRepository(Protocol):
    async def scopes(self, actor: Principal, family_id: UUID) -> list[Scope]: ...
    async def keyword(
        self, actor: Principal, family_id: UUID, question: str, top_k: int
    ) -> list[RetrievedChunk]: ...
    async def read_candidates(
        self, actor: Principal, family_id: UUID, candidates: list[Candidate], top_k: int
    ) -> list[RetrievedChunk]: ...
    async def revalidate(
        self, actor: Principal, family_id: UUID, chunks: list[RetrievedChunk]
    ) -> None: ...


class VectorSearch(Protocol):
    async def search(
        self,
        family_id: UUID,
        scopes: list[Scope],
        vector: list[float],
        top_k: int,
        threshold: float,
    ) -> list[Candidate]: ...


class ChatProvider(Protocol):
    async def answer(self, question: str, chunks: list[RetrievedChunk]) -> dict[str, object]: ...


class AnswerQuestion:
    def __init__(
        self,
        repository: EvidenceRepository,
        embeddings: EmbeddingProvider,
        vectors: VectorSearch,
        chat: ChatProvider,
        min_score: float = 0.35,
        max_context_chars: int = 6000,
        observer: RagObserver | None = None,
        rewriter: QueryRewriter | None = None,
        rewrite_timeout: float = 10.0,
        reranker: Reranker | None = None,
        rerank_timeout: float = 10.0,
    ) -> None:
        self.observer = observer if observer is not None else NullRagObserver()
        self.repository = repository
        self.embeddings = embeddings
        self.vectors = vectors
        self.chat = chat
        self.reranker = reranker
        self.rerank_timeout = rerank_timeout
        self.rewriter = rewriter
        self.rewrite_timeout = rewrite_timeout
        self.min_score = min_score
        self.max_context_chars = max_context_chars

    async def execute(
        self,
        actor: Principal,
        family_id: UUID,
        question: str,
        mode: Mode,
        top_k: int,
        generate: bool,
    ) -> RagResult:
        operation: Operation = "ask" if generate else "search"
        measurements = RagMeasurements(self.observer, mode, operation)
        started = perf_counter()
        outcome: RunOutcome = "error"
        try:
            result = await self._execute(
                actor, family_id, question, mode, top_k, generate, measurements
            )
            outcome = (
                "search_only" if not generate else "abstained" if result.abstained else "answered"
            )
            return result
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            self.observer.run(mode, operation, max(0.0, perf_counter() - started), outcome)

    async def _retrieve(
        self,
        actor: Principal,
        family_id: UUID,
        question: str,
        mode: Mode,
        top_k: int,
        scopes: list[Scope],
        measurements: RagMeasurements,
    ) -> RagResult:
        result = RagResult(timings=measurements.timings)
        if mode == "hybrid" and scopes:
            pool_size = min(24, top_k * 3)
            keyword_result = await self._retrieve(
                actor, family_id, question, "keyword", pool_size, scopes, measurements
            )
            vector_result = await self._retrieve(
                actor, family_id, question, "vector", pool_size, scopes, measurements
            )
            with measurements.stage("rrf"):
                by_id = {
                    chunk.chunk_id: chunk for chunk in keyword_result.chunks + vector_result.chunks
                }
                ranked = reciprocal_rank_fusion(
                    [
                        [chunk.chunk_id for chunk in keyword_result.chunks],
                        [chunk.chunk_id for chunk in vector_result.chunks],
                    ]
                )
                result.chunks = [
                    replace(by_id[id], score=score) for id, score in ranked[:pool_size]
                ]
            return result
        if scopes:
            if mode == "keyword":
                with measurements.stage("keyword_search"):
                    result.chunks = await self.repository.keyword(actor, family_id, question, top_k)
            else:
                with measurements.stage("embedding_identity"):
                    digest = await self.embeddings.identity()
                eligible = [
                    scope
                    for scope in scopes
                    if (
                        scope.embedding_model == self.embeddings.model
                        and scope.embedding_digest == digest
                        and scope.dimensions == self.embeddings.dimensions
                    )
                ]
                if eligible:
                    with measurements.stage("query_embedding"):
                        vector = (await self.embeddings.embed([question]))[0]
                    with measurements.stage("vector_search"):
                        candidates = await self.vectors.search(
                            family_id, eligible, vector, top_k, self.min_score
                        )
                    with measurements.stage("candidate_read"):
                        result.chunks = await self.repository.read_candidates(
                            actor, family_id, candidates, top_k
                        )
                    with measurements.stage("embedding_identity"):
                        current_digest = await self.embeddings.identity()
                    if current_digest != digest:
                        result.chunks = []
                        result.reason = "model_changed"
                else:
                    result.reason = "incompatible_index"
        return result

    async def _execute(
        self,
        actor: Principal,
        family_id: UUID,
        question: str,
        mode: Mode,
        top_k: int,
        generate: bool,
        measurements: RagMeasurements,
    ) -> RagResult:
        started = perf_counter()
        with measurements.stage("retrieval"):
            with measurements.stage("scope"):
                scopes = await self.repository.scopes(actor, family_id)
            result = await self._retrieve(
                actor, family_id, question, mode, top_k, scopes, measurements
            )
            if (
                generate
                and scopes
                and not result.chunks
                and result.reason == "no_evidence"
                and self.rewriter is not None
            ):
                rewritten = None
                try:
                    with measurements.stage("query_rewriting"):
                        async with asyncio.timeout(self.rewrite_timeout):
                            rewritten = validated_rewrite(
                                question, await self.rewriter.rewrite(question)
                            )
                except (TimeoutError, ApplicationError):
                    # Rewriting is optional; provider failure leaves the safe empty result.
                    pass
                if rewritten is not None:
                    with measurements.stage("query_retry"):
                        with measurements.stage("scope"):
                            scopes = await self.repository.scopes(actor, family_id)
                        result = await self._retrieve(
                            actor, family_id, rewritten, mode, top_k, scopes, measurements
                        )
            if (
                mode == "hybrid"
                and generate
                and len(result.chunks) > 1
                and self.reranker is not None
            ):
                # No passage reaches the reranker before live authorization is revalidated.
                with measurements.stage("acl_revalidation"):
                    await self.repository.revalidate(actor, family_id, result.chunks)
                try:
                    with measurements.stage("reranking"):
                        async with asyncio.timeout(self.rerank_timeout):
                            order = await self.reranker.rank(
                                question, [chunk.text[:600] for chunk in result.chunks]
                            )
                            if valid_order(order, len(result.chunks)) and order is not None:
                                result.chunks = [result.chunks[index] for index in order]
                                result.reranked = True
                except (TimeoutError, ApplicationError):
                    pass  # Keep deterministic RRF order on optional reranker failure.
            result.chunks = result.chunks[:top_k]
            # Return exactly the bounded excerpts passed to the generator.
            with measurements.stage("context"):
                bounded: list[RetrievedChunk] = []
                budget = self.max_context_chars
                for chunk in result.chunks:
                    if budget <= 0:
                        break
                    text = chunk.text[:budget]
                    bounded.append(replace(chunk, text=text))
                    budget -= len(text)
                result.chunks = bounded
        with measurements.stage("acl_revalidation"):
            await self.repository.revalidate(actor, family_id, result.chunks)
        if result.chunks and generate:
            with measurements.stage("generation"):
                output = await self.chat.answer(question, result.chunks)
            with measurements.stage("citation_validation"):
                answer, citations = output.get("answer"), output.get("citations")
                insufficient = output.get("insufficient_evidence")
                valid = (
                    insufficient is False
                    and isinstance(answer, str)
                    and 0 < len(answer.strip()) <= 6000
                    and isinstance(citations, list)
                    and bool(citations)
                    and all(
                        type(index) is int and 1 <= index <= len(result.chunks)
                        for index in citations
                    )
                )
                if valid and isinstance(answer, str) and isinstance(citations, list):
                    # Models may put citations only in the structured array. Render valid IDs
                    # server-side; never repair or accept an unknown reference.
                    declared = {str(index) for index in citations}
                    groups = re.findall(r"\[([0-9,\s]+)\]", answer)
                    inline = {
                        number.lstrip("0") or "0"
                        for group in groups
                        for number in re.findall(r"\d+", group)
                    }
                    if inline <= declared:
                        rendered = re.sub(
                            r"\[([0-9,\s]+)\]",
                            lambda match: " ".join(
                                "[" + (number.lstrip("0") or "0") + "]"
                                for number in re.findall(r"\d+", match.group(1))
                            ),
                            answer.strip(),
                        )
                        missing = [
                            index for index in sorted(set(citations)) if str(index) not in inline
                        ]
                        suffix = " ".join(f"[{index}]" for index in missing)
                        result.answer = rendered + (" " + suffix if suffix else "")
                        result.citations = sorted(set(citations))
                        result.abstained, result.reason = False, None
                    else:
                        result.reason = "invalid_citations"
                else:
                    result.reason = (
                        "insufficient_evidence" if insufficient is True else "invalid_model_output"
                    )
        elif result.chunks:
            result.reason = "search_only"
        with measurements.stage("acl_revalidation"):
            await self.repository.revalidate(actor, family_id, result.chunks)
        if result.abstained and result.reason != "search_only":
            result.answer = ABSTENTION_DETAILS.get(result.reason or "", ABSTENTION)
            if result.reason == "no_evidence" and not scopes:
                result.answer = "В выбранной семье нет доступных вам документов с готовым индексом. Проверьте выбранную семью, доступ и статус обработки документов."
            if result.reason == "invalid_model_output":
                result.answer += " " + " ".join(model_output_issues(output, len(result.chunks)))
        result.timings["total_ms"] = (perf_counter() - started) * 1000
        result.timings = {key: round(value, 2) for key, value in result.timings.items()}
        return result
