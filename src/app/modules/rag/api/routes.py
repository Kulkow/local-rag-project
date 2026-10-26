import asyncio
from time import perf_counter
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.document_dependencies import document_actor
from app.modules.documents.infrastructure.embedding_provider import OllamaEmbeddings
from app.modules.identity.application.contracts import Principal
from app.modules.rag.application.answering import AnswerQuestion
from app.modules.rag.infrastructure.evidence_repository import SqlEvidenceRepository
from app.modules.rag.infrastructure.providers import (
    OllamaChat,
    QdrantSearch,
    OllamaQueryRewriter,
    OllamaReranker,
)
from app.modules.shared.domain.errors import ApplicationError
from app.observability.rag_metrics import AdmissionOutcome, PrometheusRagObserver
from app.modules.rag.application.telemetry import Operation

router = APIRouter(prefix="/rag", tags=["RAG"])


class QuestionInput(BaseModel):
    family_id: UUID
    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    retrieval_mode: Literal["keyword", "vector", "hybrid"] = "vector"
    top_k: int = Field(default=5, ge=1, le=8)


class SourceView(BaseModel):
    source_id: int
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int
    text: str
    score: float


class AnswerView(BaseModel):
    answer: str
    abstained: bool
    reason: str | None
    citations: list[SourceView]
    retrieved_chunks: list[SourceView]
    retrieval_mode: Literal["keyword", "vector", "hybrid"]
    chat_model: str | None
    trace_id: str
    reranked: bool = False
    timings: dict[str, float]


async def answering_use_case(request: Request) -> AsyncIterator[AnswerQuestion]:
    config = request.app.state.settings
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(65, connect=5), follow_redirects=False
    ) as client:
        yield AnswerQuestion(
            SqlEvidenceRepository(request.app.state.db_session_factory),
            OllamaEmbeddings(
                client, config.ollama_url, config.embedding_model, config.embedding_dimensions
            ),
            QdrantSearch(client, config.qdrant_url),
            OllamaChat(client, config.ollama_url, config.chat_model),
            min_score=config.rag_min_vector_score,
            observer=request.app.state.rag_metrics,
            reranker=OllamaReranker(client, config.ollama_url, config.chat_model)
            if config.rag_reranking
            else None,
            rewriter=OllamaQueryRewriter(client, config.ollama_url, config.chat_model)
            if config.rag_query_rewriting
            else None,
        )


async def execute_query(
    body: QuestionInput,
    request: Request,
    actor: Principal,
    use_case: AnswerQuestion,
    generate: bool,
) -> AnswerView:
    gate: asyncio.Semaphore = request.app.state.rag_slots
    metrics: PrometheusRagObserver = request.app.state.rag_metrics
    operation: Operation = "ask" if generate else "search"
    waiting = perf_counter()
    admission: AdmissionOutcome = "error"
    try:
        async with asyncio.timeout(3):
            await gate.acquire()
        admission = "admitted"
    except asyncio.CancelledError:
        admission = "cancelled"
        raise
    except TimeoutError:
        admission = "throttled"
        raise ApplicationError("throttled", "Answer capacity reached; retry later") from None
    finally:
        metrics.capacity(body.retrieval_mode, operation, perf_counter() - waiting, admission)
    try:
        try:
            async with asyncio.timeout(80):
                result = await use_case.execute(
                    actor,
                    body.family_id,
                    body.question.strip(),
                    body.retrieval_mode,
                    body.top_k,
                    generate,
                )
        except TimeoutError:
            raise ApplicationError("storage_unavailable", "Question request timed out") from None
        sources = [
            SourceView(
                source_id=index,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                score=chunk.score,
            )
            for index, chunk in enumerate(result.chunks, 1)
        ]
        return AnswerView(
            answer=result.answer,
            abstained=result.abstained,
            reason=result.reason,
            citations=[source for source in sources if source.source_id in result.citations],
            retrieved_chunks=sources,
            retrieval_mode=body.retrieval_mode,
            chat_model=request.app.state.settings.chat_model if generate and sources else None,
            trace_id=request.state.request_id,
            timings=result.timings,
            reranked=result.reranked,
        )
    finally:
        gate.release()


@router.post("/ask", response_model=AnswerView)
async def ask(
    body: QuestionInput,
    request: Request,
    actor: Annotated[Principal, Depends(document_actor)],
    use_case: Annotated[AnswerQuestion, Depends(answering_use_case)],
) -> AnswerView:
    return await execute_query(body, request, actor, use_case, True)


@router.post("/search", response_model=AnswerView)
async def search(
    body: QuestionInput,
    request: Request,
    actor: Annotated[Principal, Depends(document_actor)],
    use_case: Annotated[AnswerQuestion, Depends(answering_use_case)],
) -> AnswerView:
    return await execute_query(body, request, actor, use_case, False)
