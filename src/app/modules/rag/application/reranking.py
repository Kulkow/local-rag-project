"""Rerank authorized candidates without granting the model retrieval authority."""

from typing import Protocol

from app.modules.rag.application.telemetry import TokenCounts


class Reranker(Protocol):
    async def rank(
        self, question: str, passages: list[str], *, usage: TokenCounts | None = None
    ) -> list[int] | None: ...


def valid_order(order: object, count: int) -> bool:
    return (
        isinstance(order, list)
        and len(order) == count
        and all(type(index) is int for index in order)
        and set(order) == set(range(count))
    )
