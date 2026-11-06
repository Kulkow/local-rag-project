"""Exercise the running Nginx proxy with a different public and container port."""

import os
from urllib.parse import urljoin, urlsplit

import httpx
import pytest


@pytest.fixture
def web_proxy() -> httpx.Client:
    address = os.getenv("TEST_WEB_BASE_URL")
    if not address:
        pytest.skip("Set TEST_WEB_BASE_URL to a running Web Admin proxy")
    return httpx.Client(base_url=address, timeout=10, follow_redirects=False)


@pytest.mark.parametrize("public_host", ["rag.example:3000", "rag.example:4567"])
def test_api_redirect_preserves_public_origin(web_proxy: httpx.Client, public_host: str) -> None:
    with web_proxy as client:
        response = client.get("/api", headers={"Host": public_host})
    assert response.status_code in (301, 308)
    public_origin = f"http://{public_host}"
    destination = urlsplit(urljoin(public_origin, response.headers["location"]))
    assert destination.netloc == public_host
    assert destination.path == "/api/"


def test_api_health_reaches_fastapi(web_proxy: httpx.Client) -> None:
    with web_proxy as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_internal_metrics_are_not_exposed(web_proxy: httpx.Client) -> None:
    with web_proxy as client:
        response = client.get("/api/internal/metrics")
    assert response.status_code == 404
