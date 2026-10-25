from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.main import create_app
from app.core.settings import Settings


def config() -> Settings:
    return Settings(database_url="postgresql+asyncpg://test:test@localhost/test", admin_username="operator", admin_password="test-only-password")


@pytest.mark.asyncio
async def test_health_auth_and_readiness() -> None:
    app = create_app(config())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.json() == {"status": "ok"}
            assert response.headers["X-Request-ID"]
            assert (await client.get("/ready")).status_code == 401
            assert (await client.get("/ready", auth=("operator", "wrong"))).status_code == 401
            for available in (True, False):
                with patch("app.api.health.inspect_services", AsyncMock(return_value={"postgresql": available})):
                    response = await client.get("/ready", auth=("operator", "test-only-password"))
                assert response.status_code == (200 if available else 503)
                assert response.json()["services"]["postgresql"] is available


async def test_database_outage() -> None:
    from app.api.health import check_database
    from starlette.requests import Request
    app = create_app(config())
    async with app.router.lifespan_context(app):
        request = Request({"type": "http", "app": app})
        app.state.engine = AsyncMock()
        app.state.engine.connect.side_effect = OSError("unreachable")
        assert await check_database(request) is False
