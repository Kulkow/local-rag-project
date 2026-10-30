"""SSE progress, privacy, cancellation and provider lifetime without an LLM."""

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import Request

from app.api.document_dependencies import document_actor
from app.main import create_app
from app.modules.rag.api import streaming
from app.modules.rag.api.routes import QuestionInput
from app.modules.rag.application.answering import AnswerQuestion, RetrievedChunk, Scope
from app.modules.shared.domain.errors import ApplicationError


@pytest.fixture
def stream_setup(monkeypatch: pytest.MonkeyPatch) -> tuple:
    app = create_app()
    app.state.settings = SimpleNamespace(chat_model="synthetic")
    app.state.rag_slots = asyncio.Semaphore(1)
    repository, embeddings, vectors, chat = (AsyncMock() for _ in range(4))
    document, generation = uuid4(), uuid4()
    repository.scopes.return_value = [Scope(document, generation, "synthetic")]
    repository.keyword.return_value = [
        RetrievedChunk(uuid4(), document, generation, "private.pdf", 1, "PRIVATE TEXT", 1.0)
    ]
    chat.answer.return_value = {
        "answer": "Answer [1]",
        "citations": [1],
        "insufficient_evidence": False,
    }
    use_case = AnswerQuestion(repository, embeddings, vectors, chat, observer=app.state.rag_metrics)
    lifecycle: list[str] = []

    async def cases(request: Request) -> AsyncIterator[AnswerQuestion]:
        lifecycle.append("open")
        try:
            yield use_case
        finally:
            lifecycle.append("closed")

    monkeypatch.setattr(streaming, "answering_use_case", cases)
    app.dependency_overrides[document_actor] = lambda: AsyncMock()
    return app, repository, chat, lifecycle


def decode(frame: str) -> dict:
    return json.loads(frame.split("data: ", 1)[1])


@pytest.mark.parametrize(
    "outcome",
    ["answer", "search", "provider", "acl", "revoked", "capacity", "internal", "deadline"],
)
async def test_stream_http_terminal_events(
    stream_setup: tuple, outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, repository, chat, lifecycle = stream_setup
    if outcome == "provider":
        chat.answer.side_effect = ApplicationError("storage_unavailable", "Model unavailable")
    elif outcome == "acl":
        repository.scopes.side_effect = ApplicationError("not_found", "Family not found")
    elif outcome == "revoked":
        repository.revalidate.side_effect = [None, ApplicationError("forbidden", "Access revoked")]
    elif outcome == "internal":
        chat.answer.side_effect = RuntimeError("PRIVATE PROVIDER FAILURE")
    elif outcome == "capacity":
        app.state.rag_slots = AsyncMock()
        app.state.rag_slots.acquire.side_effect = TimeoutError()
    elif outcome == "deadline":
        original = asyncio.timeout
        monkeypatch.setattr(
            asyncio, "timeout", lambda seconds: original(0.01 if seconds == 80 else seconds)
        )

        async def slow(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(1)

        chat.answer.side_effect = slow
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/rag/search/stream" if outcome == "search" else "/rag/ask/stream",
            json={
                "family_id": str(uuid4()),
                "question": "PRIVATE QUESTION",
                "retrieval_mode": "keyword",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    events = [decode(frame) for frame in response.text.strip().split("\n\n")]
    assert events[0]["event"] == "progress"
    assert "PRIVATE" not in json.dumps(events[:-1])
    assert all(event["trace_id"] == response.headers["x-request-id"] for event in events)
    terminal = events[-1]
    assert terminal["event"] == ("result" if outcome in {"answer", "search"} else "error")
    if terminal["event"] == "error":
        assert "PRIVATE" not in response.text and "private.pdf" not in response.text
        assert terminal["result"] is None
    else:
        assert terminal["result"]["timings"]["request_ms"] >= 0
    if outcome == "search":
        chat.answer.assert_not_awaited()
        assert "generation_ms" not in terminal["timings"]
    if outcome == "deadline":
        assert terminal["code"] == "storage_unavailable"
        assert terminal["timings"]["generation_ms"] > 0
    assert lifecycle == ["open", "closed"]
    if outcome != "capacity":
        assert not app.state.rag_slots.locked()


async def test_disconnect_cancels_running_model_and_closes_client(stream_setup: tuple) -> None:
    app, _, chat, lifecycle = stream_setup
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(*args: object, **kwargs: object) -> None:
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    chat.answer.side_effect = slow
    request = Request({"type": "http", "app": app})
    request.state.request_id = "trace"
    body = QuestionInput(family_id=uuid4(), question="secret", retrieval_mode="keyword")
    events = streaming.rag_events(body, request, AsyncMock(), True)
    assert decode(await anext(events))["waiting"]
    await asyncio.wait_for(entered.wait(), 1)
    progress = decode(await anext(events))
    assert "generation" in progress["active_stages"]
    assert progress["timings"]["generation_ms"] > 0
    assert progress["result"] is None and "secret" not in json.dumps(progress)
    await events.aclose()
    assert cancelled.is_set() and lifecycle == ["open", "closed"]
    assert not app.state.rag_slots.locked()


async def test_sse_authentication_and_openapi(stream_setup: tuple) -> None:
    app, repository, _, lifecycle = stream_setup

    def denied() -> None:
        raise ApplicationError("unauthorized", "Authentication required")

    app.dependency_overrides[document_actor] = denied
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/rag/ask/stream", json={"family_id": str(uuid4()), "question": "secret"}
        )
    assert response.status_code == 401 and lifecycle == []
    repository.scopes.assert_not_awaited()
    content = app.openapi()["paths"]["/rag/ask/stream"]["post"]["responses"]["200"]["content"]
    assert content["text/event-stream"]["schema"]["$ref"].endswith("/RagStreamEvent")


async def test_asgi_disconnect_releases_capacity(stream_setup: tuple) -> None:
    app, _, chat, lifecycle = stream_setup
    disconnected, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(*args: object, **kwargs: object) -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    chat.answer.side_effect = slow
    scope = {"type": "http", "app": app, "method": "POST", "path": "/rag/ask/stream", "headers": []}
    request = Request(scope)
    request.state.request_id = "trace"
    response = await streaming.ask_stream(
        QuestionInput(family_id=uuid4(), question="secret", retrieval_mode="keyword"),
        request,
        AsyncMock(),
    )

    async def receive() -> dict:
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            event = decode(message["body"].decode())
            if "generation" in event["active_stages"]:
                disconnected.set()

    await asyncio.wait_for(response(scope, receive, send), 2)
    assert cancelled.is_set()
    assert lifecycle == ["open", "closed"]
    assert not app.state.rag_slots.locked()
