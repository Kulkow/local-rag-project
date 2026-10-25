import os

import httpx
import pytest

from app.core.settings import Settings
from app.main import create_app


async def test_api_with_migrated_postgresql() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated PostgreSQL database")
    app = create_app(Settings(database_url=url, admin_username="test-admin", admin_password="test-password"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/ready", auth=("test-admin", "test-password"))
            assert response.status_code in (200, 503)
            assert response.json()["services"]["postgresql"] is True
