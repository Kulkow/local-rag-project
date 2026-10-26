from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from prometheus_client.parser import text_string_to_metric_families

from app.modules.rag.api.routes import QuestionInput, execute_query
from app.modules.shared.domain.errors import ApplicationError
from app.observability.rag_metrics import PrometheusRagObserver


def test_isolated_registries_and_bounded_metric_labels() -> None:
    first, second = PrometheusRagObserver(), PrometheusRagObserver()
    first.stage("vector", "ask", "vector_search", 0.025, "success")
    families = list(text_string_to_metric_families(first.render().decode()))
    assert any(family.name == "rag_stage_duration_seconds" for family in families)
    assert "vector_search" not in second.render().decode()
    assert all(
        set(sample.labels) <= {"mode", "operation", "stage", "outcome", "le"}
        for family in families
        for sample in family.samples
    )


async def test_capacity_timeout_is_measured_without_calling_rag() -> None:
    metrics = PrometheusRagObserver()
    app = FastAPI()
    app.state.rag_metrics = metrics
    app.state.rag_slots = AsyncMock()
    app.state.rag_slots.acquire.side_effect = TimeoutError()
    request = Request({"type": "http", "app": app})
    use_case = AsyncMock()
    with pytest.raises(ApplicationError) as error:
        await execute_query(
            QuestionInput(family_id=uuid4(), question="private"),
            request,
            AsyncMock(),
            use_case,
            True,
        )
    assert error.value.code == "throttled"
    use_case.execute.assert_not_awaited()
    app.state.rag_slots.release.assert_not_called()
    assert (
        metrics.registry.get_sample_value(
            "rag_capacity_wait_seconds_count",
            {"mode": "vector", "operation": "ask", "outcome": "throttled"},
        )
        == 1
    )
    assert "private" not in metrics.render().decode()


async def test_metrics_endpoint_has_isolated_app_state_and_no_openapi_entry() -> None:
    import httpx
    from app.main import create_app

    app = create_app()
    app.state.rag_metrics.run("keyword", "search", 0.01, "search_only")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/internal/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "rag_requests_total" in response.text
    assert "/internal/metrics" not in app.openapi()["paths"]
    assert "search_only" not in create_app().state.rag_metrics.render().decode()
