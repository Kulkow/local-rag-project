"""Durable job identity, separate from original and extraction state."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ProcessingStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessingJob:
    document_id: UUID
    requested_by: UUID
    generation: UUID
    status: ProcessingStatus
    attempts: int = 0
    error_code: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reindex: bool = False
