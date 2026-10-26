"""RAG orchestration with pre-retrieval ACL scope and validated citation mapping."""

import re
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Literal, Protocol
from uuid import UUID

from app.modules.documents.application.indexing import EmbeddingProvider
from app.modules.identity.application.contracts import Principal

Mode = Literal["keyword", "vector"]
ABSTENTION = "Недостаточно подтверждённых данных в доступных документах."


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
    ) -> None:
        self.repository = repository
        self.embeddings = embeddings
        self.vectors = vectors
        self.chat = chat
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
        started = perf_counter()
        scopes = await self.repository.scopes(actor, family_id)
        result = RagResult()
        if scopes:
            if mode == "keyword":
                result.chunks = await self.repository.keyword(actor, family_id, question, top_k)
            else:
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
                    vector = (await self.embeddings.embed([question]))[0]
                    candidates = await self.vectors.search(
                        family_id, eligible, vector, top_k, self.min_score
                    )
                    result.chunks = await self.repository.read_candidates(
                        actor, family_id, candidates, top_k
                    )
                    if await self.embeddings.identity() != digest:
                        result.chunks = []
                        result.reason = "model_changed"
                else:
                    result.reason = "incompatible_index"
        # Return exactly the bounded excerpts passed to the generator.
        bounded: list[RetrievedChunk] = []
        budget = self.max_context_chars
        for chunk in result.chunks:
            if budget <= 0:
                break
            text = chunk.text[:budget]
            bounded.append(replace(chunk, text=text))
            budget -= len(text)
        result.chunks = bounded
        result.timings["retrieval_ms"] = round((perf_counter() - started) * 1000, 2)
        await self.repository.revalidate(actor, family_id, result.chunks)
        if result.chunks and generate:
            generation_started = perf_counter()
            output = await self.chat.answer(question, result.chunks)
            result.timings["generation_ms"] = round((perf_counter() - generation_started) * 1000, 2)
            answer, citations = output.get("answer"), output.get("citations")
            insufficient = output.get("insufficient_evidence")
            valid = (
                insufficient is False
                and isinstance(answer, str)
                and 0 < len(answer.strip()) <= 6000
                and isinstance(citations, list)
                and bool(citations)
                and all(
                    type(index) is int and 1 <= index <= len(result.chunks) for index in citations
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
        await self.repository.revalidate(actor, family_id, result.chunks)
        result.timings["total_ms"] = round((perf_counter() - started) * 1000, 2)
        return result
