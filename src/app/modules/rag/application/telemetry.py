"""Content-free RAG measurements; adapters implement the observer port."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Literal, Protocol

Mode = Literal["keyword", "vector", "hybrid"]
Operation = Literal["ask", "search"]
Stage = Literal[
    "retrieval",
    "scope",
    "embedding_identity",
    "query_embedding",
    "query_rewriting",
    "query_retry",
    "keyword_search",
    "vector_search",
    "candidate_read",
    "rrf",
    "reranking",
    "context",
    "acl_revalidation",
    "generation",
    "citation_validation",
]
Outcome = Literal["success", "error", "cancelled"]
RunOutcome = Literal["answered", "abstained", "search_only", "error", "cancelled"]


class RagObserver(Protocol):
    def stage(
        self, mode: Mode, operation: Operation, stage: Stage, seconds: float, outcome: Outcome
    ) -> None: ...
    def run(
        self, mode: Mode, operation: Operation, seconds: float, outcome: RunOutcome
    ) -> None: ...


class NullRagObserver:
    def stage(
        self, mode: Mode, operation: Operation, stage: Stage, seconds: float, outcome: Outcome
    ) -> None:
        pass

    def run(self, mode: Mode, operation: Operation, seconds: float, outcome: RunOutcome) -> None:
        pass


class RagMeasurements:
    def __init__(self, observer: RagObserver, mode: Mode, operation: Operation) -> None:
        self.observer = observer
        self.mode = mode
        self.operation = operation
        self.timings: dict[str, float] = {}

    @contextmanager
    def stage(self, name: Stage) -> Iterator[None]:
        started = perf_counter()
        outcome: Outcome = "success"
        try:
            yield
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            seconds = max(0.0, perf_counter() - started)
            key = f"{name}_ms"
            self.timings[key] = self.timings.get(key, 0.0) + seconds * 1000
            self.observer.stage(self.mode, self.operation, name, seconds, outcome)
