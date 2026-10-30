"""Content-free RAG measurements; adapters implement the observer port."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
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
LlmStage = Literal["generation", "query_rewriting", "reranking"]


@dataclass
class TokenCounts:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class LlmCallUsage(TokenCounts):
    stage: LlmStage = "generation"


@dataclass
class LlmUsage(TokenCounts):
    calls: list[LlmCallUsage] = field(default_factory=list)


class RagObserver(Protocol):
    def tokens(self, mode: Mode, operation: Operation, usage: LlmCallUsage) -> None: ...

    def stage(
        self, mode: Mode, operation: Operation, stage: Stage, seconds: float, outcome: Outcome
    ) -> None: ...
    def run(
        self, mode: Mode, operation: Operation, seconds: float, outcome: RunOutcome
    ) -> None: ...


class NullRagObserver:
    def tokens(self, mode: Mode, operation: Operation, usage: LlmCallUsage) -> None:
        pass

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
        self.active: list[tuple[Stage, float]] = []
        self.llm_calls: list[LlmCallUsage] = []

    def usage_snapshot(self) -> LlmUsage:
        def total(values: list[int | None]) -> int | None:
            return None if None in values else sum(value for value in values if value is not None)

        return LlmUsage(
            input_tokens=total([call.input_tokens for call in self.llm_calls]),
            output_tokens=total([call.output_tokens for call in self.llm_calls]),
            calls=[
                LlmCallUsage(call.input_tokens, call.output_tokens, call.stage)
                for call in self.llm_calls
            ],
        )

    @contextmanager
    def llm_call(self, stage: LlmStage) -> Iterator[TokenCounts]:
        usage = LlmCallUsage(stage=stage)
        self.llm_calls.append(usage)
        try:
            yield usage
        finally:
            self.observer.tokens(self.mode, self.operation, usage)

    def snapshot(self) -> dict[str, float]:
        """Completed durations plus elapsed time of currently running stages."""
        timings = dict(self.timings)
        now = perf_counter()
        for name, started in self.active:
            key = f"{name}_ms"
            timings[key] = timings.get(key, 0.0) + max(0.0, now - started) * 1000
        return {key: round(value, 2) for key, value in timings.items()}

    @contextmanager
    def stage(self, name: Stage) -> Iterator[None]:
        started = perf_counter()
        self.active.append((name, started))
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
            self.active.pop()
            seconds = max(0.0, perf_counter() - started)
            key = f"{name}_ms"
            self.timings[key] = self.timings.get(key, 0.0) + seconds * 1000
            self.observer.stage(self.mode, self.operation, name, seconds, outcome)
