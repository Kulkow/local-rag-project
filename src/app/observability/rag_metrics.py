"""Process-local Prometheus adapter with fixed labels and no request content."""

from typing import Literal, get_args

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from app.modules.rag.application.telemetry import (
    Mode,
    Operation,
    Outcome,
    RunOutcome,
    Stage,
    LlmCallUsage,
    LlmStage,
)

BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 90)
AdmissionOutcome = Literal["admitted", "throttled", "cancelled", "error"]


class PrometheusRagObserver:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.llm_tokens = Counter(
            "rag_llm_tokens_total",
            "Provider-reported LLM tokens; missing usage is not estimated.",
            ("mode", "operation", "stage", "direction"),
            registry=self.registry,
        )
        self.stages = Histogram(
            "rag_stage_duration_seconds",
            "Executed RAG stages, including failures and cancellation.",
            ("mode", "operation", "stage", "outcome"),
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.duration = Histogram(
            "rag_request_duration_seconds",
            "Application runtime of admitted RAG requests, excluding capacity wait.",
            ("mode", "operation", "outcome"),
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.requests = Counter(
            "rag_requests_total",
            "Completed admitted RAG attempts by outcome.",
            ("mode", "operation", "outcome"),
            registry=self.registry,
        )
        self.wait = Histogram(
            "rag_capacity_wait_seconds",
            "Time waiting for RAG admission, including rejected requests.",
            ("mode", "operation", "outcome"),
            buckets=BUCKETS,
            registry=self.registry,
        )

    def tokens(self, mode: Mode, operation: Operation, usage: LlmCallUsage) -> None:
        if (
            mode not in get_args(Mode)
            or operation not in get_args(Operation)
            or usage.stage not in get_args(LlmStage)
        ):
            return
        for direction, count in (("input", usage.input_tokens), ("output", usage.output_tokens)):
            if type(count) is int and count >= 0:
                self.llm_tokens.labels(mode, operation, usage.stage, direction).inc(count)

    def stage(
        self, mode: Mode, operation: Operation, stage: Stage, seconds: float, outcome: Outcome
    ) -> None:
        if (
            mode not in get_args(Mode)
            or operation not in get_args(Operation)
            or stage not in get_args(Stage)
            or outcome not in get_args(Outcome)
        ):
            return
        self.stages.labels(mode, operation, stage, outcome).observe(seconds)

    def run(self, mode: Mode, operation: Operation, seconds: float, outcome: RunOutcome) -> None:
        if (
            mode not in get_args(Mode)
            or operation not in get_args(Operation)
            or outcome not in get_args(RunOutcome)
        ):
            return
        self.duration.labels(mode, operation, outcome).observe(seconds)
        self.requests.labels(mode, operation, outcome).inc()

    def capacity(
        self, mode: Mode, operation: Operation, seconds: float, outcome: AdmissionOutcome
    ) -> None:
        if (
            mode not in get_args(Mode)
            or operation not in get_args(Operation)
            or outcome not in get_args(AdmissionOutcome)
        ):
            return
        self.wait.labels(mode, operation, outcome).observe(seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)
