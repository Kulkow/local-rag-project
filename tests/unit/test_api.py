from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.core.settings import Settings
from app.main import create_app
from app.modules.operations.api.routes import readiness_use_case
from app.modules.operations.application.readiness import InspectReadiness
from app.modules.operations.infrastructure.probes import DatabaseProbe


def config() -> Settings:
    return Settings(
        jwt_secret="test-signing-key-for-jwt-only-123456",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        admin_username="operator",
        admin_password="test-only-password",
    )


@pytest.mark.asyncio
async def test_health_auth_and_readiness() -> None:
    app = create_app(config())
    async with app.router.lifespan_context(app):
        probe = Mock()
        probe.check = AsyncMock(return_value=True)
        use_case = InspectReadiness({"postgresql": probe})
        app.dependency_overrides[readiness_use_case] = lambda: use_case
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
            assert response.json() == {"status": "ok"}
            assert response.headers["X-Request-ID"]
            assert response.headers["Server-Timing"]
            assert (await client.get("/ready")).status_code == 401
            assert (await client.get("/ready", auth=("operator", "wrong"))).status_code == 401
            probe.check.assert_not_called()
            for available in (True, False):
                probe.check.return_value = available
                response = await client.get("/ready", auth=("operator", "test-only-password"))
                assert response.status_code == (200 if available else 503)
                assert response.json() == {
                    "status": "ready" if available else "degraded",
                    "services": {"postgresql": available},
                }


async def test_database_outage() -> None:
    engine = Mock()
    engine.connect.side_effect = OSError("unreachable")
    result = await InspectReadiness({"postgresql": DatabaseProbe(engine)}).execute()
    assert result.services == {"postgresql": False}


def test_openapi_contract_is_unchanged() -> None:
    schema = create_app().openapi()
    assert {"/health", "/ready"}.issubset(schema["paths"])
    for path, model in (("/health", "Health"), ("/ready", "Readiness")):
        operation = schema["paths"][path]["get"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{model}"
        }
        assert "parameters" not in operation
        assert "requestBody" not in operation
    assert {"HTTPBasic": []} in schema["paths"]["/ready"]["get"]["security"]
    assert {"HTTPBearer": []} in schema["paths"]["/ready"]["get"]["security"]
    assert "security" not in schema["paths"]["/health"]["get"]
    assert schema["components"]["securitySchemes"]["HTTPBasic"] == {
        "type": "http",
        "scheme": "basic",
    }
    models = schema["components"]["schemas"]
    assert set(models["Health"]["properties"]) == {"status"}
    assert models["Health"]["properties"]["status"]["const"] == "ok"
    assert set(models["Readiness"]["properties"]) == {"status", "services"}
    assert models["Readiness"]["properties"]["status"]["enum"] == ["ready", "degraded"]
    assert models["Readiness"]["properties"]["services"]["additionalProperties"] == {
        "type": "boolean"
    }
