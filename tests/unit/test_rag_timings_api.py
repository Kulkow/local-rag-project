"""Per-request timing diagnostics survive provider failures and deadlines."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.api.document_dependencies import document_actor
from app.main import create_app
from app.modules.rag.api.routes import answering_use_case
from app.modules.rag.application.answering import AnswerQuestion, RetrievedChunk, Scope
from app.modules.shared.domain.errors import ApplicationError


@pytest.mark.parametrize("outcome", ["answer", "search", "provider", "deadline", "acl", "capacity"])
async def test_rag_timings_in_http_responses(outcome: str, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    app.state.settings = SimpleNamespace(chat_model="synthetic")
    app.state.rag_slots = asyncio.Semaphore(1)
    repository, embeddings, vectors, chat = (AsyncMock() for _ in range(4))
    document, generation = uuid4(), uuid4()
    repository.scopes.return_value = [Scope(document, generation, "synthetic")]
    repository.keyword.return_value = [
        RetrievedChunk(uuid4(), document, generation, "private.pdf", 1, "PRIVATE CONTENT", 1.0)
    ]
    chat.answer.return_value = {
        "answer": "Answer [1]",
        "citations": [1],
        "insufficient_evidence": False,
    }
    if outcome == "provider":
        chat.answer.side_effect = ApplicationError("storage_unavailable", "Model unavailable")
    elif outcome == "acl":
        repository.scopes.side_effect = ApplicationError("not_found", "Family not found")
    elif outcome == "deadline":
        original_timeout = asyncio.timeout
        monkeypatch.setattr(
            asyncio, "timeout", lambda seconds: original_timeout(0.02 if seconds == 80 else seconds)
        )

        async def slow_answer(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(1)

        chat.answer.side_effect = slow_answer
    elif outcome == "capacity":
        app.state.rag_slots = AsyncMock()
        app.state.rag_slots.acquire.side_effect = TimeoutError()

    use_case = AnswerQuestion(repository, embeddings, vectors, chat)
    app.dependency_overrides[document_actor] = lambda: AsyncMock()
    app.dependency_overrides[answering_use_case] = lambda: use_case
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/rag/search" if outcome == "search" else "/rag/ask",
            json={
                "family_id": str(uuid4()),
                "question": "PRIVATE QUESTION",
                "retrieval_mode": "keyword",
            },
        )
        data = response.json()
        timings = data["timings"]
        assert data["trace_id"] == response.headers["x-request-id"]
        assert timings["request_ms"] >= timings["capacity_wait_ms"] >= 0
        assert all(isinstance(value, int | float) and value >= 0 for value in timings.values())
        assert "vector_search_ms" not in timings
        if outcome == "capacity":
            assert response.status_code == 429
            assert set(timings) == {"capacity_wait_ms", "request_ms"}
            repository.scopes.assert_not_awaited()
            app.state.rag_slots.release.assert_not_called()
        else:
            assert not app.state.rag_slots.locked()
            assert timings["request_ms"] >= timings["total_ms"] >= timings["retrieval_ms"]
            assert "scope_ms" in timings
            if outcome in {"answer", "search"}:
                assert response.status_code == 200
                assert ("generation_ms" in timings) == (outcome == "answer")
            else:
                assert response.status_code == (404 if outcome == "acl" else 503)
                assert "PRIVATE" not in response.text and "private.pdf" not in response.text
                assert "citation_validation_ms" not in timings
                assert ("generation_ms" in timings) == (outcome != "acl")

        # A later denied request must not inherit timing data from this request.
        def denied_actor() -> None:
            raise ApplicationError("unauthorized", "Authentication required")

        app.dependency_overrides[document_actor] = denied_actor
        denied = await client.post(
            "/rag/ask", json={"family_id": str(uuid4()), "question": "secret"}
        )
        assert denied.status_code == 401 and "timings" not in denied.json()
