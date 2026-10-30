"""Authenticated SSE progress; publish evidence only after final authorization."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.document_dependencies import document_actor
from app.modules.identity.application.contracts import Principal
from app.modules.rag.api.routes import (
    ERROR_RESPONSES,
    AnswerView,
    QuestionInput,
    answering_use_case,
    execute_query,
)
from app.modules.rag.application.telemetry import RagMeasurements, Stage, LlmUsage
from app.modules.shared.domain.errors import ApplicationError

router = APIRouter(prefix="/rag", tags=["RAG"])


class RagStreamEvent(BaseModel):
    llm_usage: LlmUsage | None = None
    event: Literal["progress", "result", "error"]
    trace_id: str
    timings: dict[str, float]
    active_stages: list[Stage] = Field(default_factory=list)
    waiting: bool = False
    elapsed_ms: float
    result: AnswerView | None = None
    detail: str | None = None
    code: str | None = None


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RagErrorView"}}}
    }
    for code in ERROR_RESPONSES
}
STREAM_RESPONSES[200] = {
    "description": "SSE frames; each data field contains a RagStreamEvent JSON object.",
    "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/RagStreamEvent"}}},
}


async def rag_events(
    body: QuestionInput, request: Request, actor: Principal, generate: bool
) -> AsyncIterator[str]:
    started = perf_counter()
    measurements = RagMeasurements(
        request.app.state.rag_metrics, body.retrieval_mode, "ask" if generate else "search"
    )

    def event(kind: Literal["progress", "result", "error"], **fields: object) -> str:
        payload = RagStreamEvent.model_validate(
            {
                "event": kind,
                "trace_id": request.state.request_id,
                "timings": measurements.snapshot(),
                "llm_usage": measurements.usage_snapshot(),
                "active_stages": [name for name, _ in measurements.active],
                "waiting": kind == "progress" and "capacity_wait_ms" not in measurements.timings,
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                **fields,
            }
        )
        return f"event: {kind}\ndata: {payload.model_dump_json()}\n\n"

    async def run() -> AnswerView:
        # FastAPI 0.115 closes yield dependencies before streaming the response.
        # Own the HTTP client inside the task, including cancellation and cleanup.
        async with aclosing(answering_use_case(request)) as cases:
            use_case = await anext(cases)
            return await execute_query(body, request, actor, use_case, generate, measurements)

    task = asyncio.create_task(run())
    try:
        yield event("progress")
        while not task.done():
            await asyncio.wait({task}, timeout=0.25)
            if not task.done():
                yield event("progress")
        answer = await task
        yield event("result", result=answer)
    except ApplicationError as exc:
        yield event("error", detail=str(exc), code=exc.code)
    except Exception:
        # Never forward provider responses, document content or internal errors.
        yield event("error", detail="RAG request failed; retry later", code="internal_error")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


@router.post(
    "/ask/stream",
    response_class=EventStreamResponse,
    response_model=RagStreamEvent,
    responses=STREAM_RESPONSES,
)
async def ask_stream(
    body: QuestionInput, request: Request, actor: Annotated[Principal, Depends(document_actor)]
) -> EventStreamResponse:
    return EventStreamResponse(
        rag_events(body, request, actor, True),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


@router.post(
    "/search/stream",
    response_class=EventStreamResponse,
    response_model=RagStreamEvent,
    responses=STREAM_RESPONSES,
)
async def search_stream(
    body: QuestionInput, request: Request, actor: Annotated[Principal, Depends(document_actor)]
) -> EventStreamResponse:
    return EventStreamResponse(
        rag_events(body, request, actor, False),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
