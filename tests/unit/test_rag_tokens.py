"""Usage comes from provider metadata and survives invalid answers and failures."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.api.document_dependencies import document_actor
from app.main import create_app
from app.modules.rag.api import streaming
from app.modules.rag.api.routes import answering_use_case
from app.modules.rag.application.answering import AnswerQuestion, RetrievedChunk, Scope
from app.modules.rag.application.telemetry import RagMeasurements, TokenCounts
from app.modules.rag.infrastructure.providers import OllamaChat, OllamaQueryRewriter, OllamaReranker
from app.modules.shared.domain.errors import ApplicationError
from app.observability.rag_metrics import PrometheusRagObserver


@pytest.mark.parametrize("provider", ["chat", "rewrite", "rerank"])
@pytest.mark.parametrize("counts", [(123, 45), (0, 0), (None, None), (-1, True), ("12", 1.5)])
async def test_provider_reads_only_valid_metadata_even_for_invalid_output(
    provider: str, counts: tuple[object, object]
) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "prompt_eval_count": counts[0],
                "eval_count": counts[1],
                "message": {"content": "invalid PRIVATE output", "thinking": "PRIVATE reasoning"},
            },
        )

    usage = TokenCounts()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        if provider == "chat":
            assert (
                await OllamaChat(client, "http://ollama", "fake").answer("private", [], usage=usage)
                == {}
            )
        elif provider == "rewrite":
            assert (
                await OllamaQueryRewriter(client, "http://ollama", "fake").rewrite(
                    "private", usage=usage
                )
                is None
            )
        else:
            assert (
                await OllamaReranker(client, "http://ollama", "fake").rank(
                    "private", [], usage=usage
                )
                is None
            )
    expected = [n if type(n) is int and n >= 0 else None for n in counts]
    assert [usage.input_tokens, usage.output_tokens] == expected
    assert "PRIVATE" not in str(asdict(usage))


def test_usage_aggregates_calls_without_turning_unknown_into_zero() -> None:
    metrics = PrometheusRagObserver()
    measurements = RagMeasurements(metrics, "hybrid", "ask")
    assert asdict(measurements.usage_snapshot()) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "calls": [],
    }
    for stage in ("query_rewriting", "reranking", "generation", "generation"):
        with measurements.llm_call(stage) as usage:
            usage.input_tokens, usage.output_tokens = 100, 20
    snapshot = measurements.usage_snapshot()
    assert snapshot.input_tokens == 400 and snapshot.output_tokens == 80
    with pytest.raises(TimeoutError), measurements.llm_call("generation") as usage:
        usage.input_tokens = 10
        raise TimeoutError()
    assert measurements.usage_snapshot().input_tokens == 410
    assert measurements.usage_snapshot().output_tokens is None
    assert len(snapshot.calls) == 4  # Snapshot isn't a live reference.
    assert (
        metrics.registry.get_sample_value(
            "rag_llm_tokens_total",
            {"mode": "hybrid", "operation": "ask", "stage": "generation", "direction": "input"},
        )
        == 210
    )
    assert (
        metrics.registry.get_sample_value(
            "rag_llm_tokens_total",
            {"mode": "hybrid", "operation": "ask", "stage": "generation", "direction": "output"},
        )
        == 40
    )
    assert "PRIVATE" not in metrics.render().decode()
    assert RagMeasurements(metrics, "keyword", "search").usage_snapshot().calls == []


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "outcome", ["answer", "search", "invalid", "revoked", "timeout", "no_evidence"]
)
async def test_api_usage_and_request_isolation(
    stream: bool, outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from collections.abc import AsyncIterator
    from fastapi import Request

    app = create_app()
    app.state.rag_slots = asyncio.Semaphore(1)
    app.state.settings = SimpleNamespace(chat_model="fake")
    repository = AsyncMock()
    document, generation = uuid4(), uuid4()
    repository.scopes.return_value = [Scope(document, generation, "synthetic")]
    repository.keyword.return_value = (
        []
        if outcome == "no_evidence"
        else [RetrievedChunk(uuid4(), document, generation, "private.pdf", 1, "PRIVATE TEXT", 1.0)]
    )
    if outcome == "revoked":
        repository.revalidate.side_effect = [None, ApplicationError("forbidden", "Access revoked")]

    def provider(request: httpx.Request) -> httpx.Response:
        if outcome == "timeout":
            raise httpx.ReadTimeout("PRIVATE")
        content = (
            "invalid"
            if outcome == "invalid"
            else json.dumps(
                {
                    "answer": "Answer [1]",
                    "citations": [1],
                    "insufficient_evidence": False,
                }
            )
        )
        return httpx.Response(
            200,
            json={
                "prompt_eval_count": 120,
                "eval_count": 30,
                "message": {"content": content},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as llm:
        use_case = AnswerQuestion(
            repository, AsyncMock(), AsyncMock(), OllamaChat(llm, "http://ollama", "fake")
        )

        async def cases(request: Request) -> AsyncIterator[AnswerQuestion]:
            yield use_case

        app.dependency_overrides[document_actor] = lambda: AsyncMock()
        app.dependency_overrides[answering_use_case] = cases
        monkeypatch.setattr(streaming, "answering_use_case", cases)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = (
                "/rag/"
                + ("search" if outcome == "search" else "ask")
                + ("/stream" if stream else "")
            )
            response = await client.post(
                path,
                json={
                    "family_id": str(uuid4()),
                    "question": "PRIVATE",
                    "retrieval_mode": "keyword",
                },
            )
            if stream:
                data = json.loads(response.text.strip().split("\n\n")[-1].split("data: ")[1])
                assert data["event"] == ("error" if outcome in {"revoked", "timeout"} else "result")
                if data["event"] == "result":
                    assert data["llm_usage"] == data["result"]["llm_usage"]
            else:
                data = response.json()
            usage = data["llm_usage"]
            if outcome in {"search", "no_evidence"}:
                assert usage == {"input_tokens": 0, "output_tokens": 0, "calls": []}
            else:
                assert usage["input_tokens"] == (None if outcome == "timeout" else 120)
                assert usage["output_tokens"] == (None if outcome == "timeout" else 30)
                assert len(usage["calls"]) == 1 and usage["calls"][0]["stage"] == "generation"
            if outcome in {"revoked", "timeout"}:
                assert "PRIVATE" not in response.text

            def denied() -> None:
                raise ApplicationError("unauthorized", "Authentication required")

            app.dependency_overrides[document_actor] = denied
            response = await client.post(
                path, json={"family_id": str(uuid4()), "question": "private"}
            )
            assert response.status_code == 401 and "llm_usage" not in response.json()
