"""Ollama adapter; HTTP content and provider exceptions are never exposed."""

import math

import httpx

from app.modules.shared.domain.errors import ApplicationError


class OllamaEmbeddings:
    def __init__(
        self, client: httpx.AsyncClient, base_url: str, model: str, dimensions: int
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions

    async def identity(self) -> str:
        try:
            response = await self.client.get(self.base_url + "/api/tags")
            response.raise_for_status()
            canonical = self.model if ":" in self.model else self.model + ":latest"
            for item in response.json()["models"]:
                if item.get("name") in (self.model, canonical) or item.get("model") in (
                    self.model,
                    canonical,
                ):
                    digest = item.get("digest")
                    if isinstance(digest, str) and 0 < len(digest) <= 128:
                        return digest
            raise ApplicationError("invalid", "Configured embedding model is not installed")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ApplicationError(
                "storage_unavailable", "Embedding model metadata is unavailable"
            ) from None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.post(
                self.base_url + "/api/embed",
                json={
                    "model": self.model,
                    "input": texts,
                    "truncate": False,
                },
            )
            if 400 <= response.status_code < 500:
                raise ApplicationError(
                    "invalid",
                    "Embedding model rejected input; verify model and chunk configuration",
                )
            response.raise_for_status()
            raw = response.json()["embeddings"]
            if not isinstance(raw, list) or len(raw) != len(texts):
                raise ValueError("Embedding count mismatch")
            result: list[list[float]] = []
            for vector in raw:
                if not isinstance(vector, list) or len(vector) != self.dimensions:
                    raise ApplicationError(
                        "invalid", "Embedding dimensions do not match configuration"
                    )
                if any(
                    type(value) not in (int, float) or not math.isfinite(value) for value in vector
                ):
                    raise ValueError("Invalid vector")
                values = [float(value) for value in vector]
                if not any(values):
                    raise ValueError("Zero vector")
                result.append(values)
            return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ApplicationError(
                "storage_unavailable", "Embedding request failed or returned invalid vectors"
            ) from None
