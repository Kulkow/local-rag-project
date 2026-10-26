"""Process one durable job. Infrastructure owns locking and scheduling."""

from typing import Protocol
from uuid import UUID

from app.modules.documents.application.extraction import ExtractionRepository, ExtractorRegistry
from app.modules.documents.application.upload import FamilyAccess
from app.modules.documents.domain.entities import DocumentStatus
from app.modules.identity.application.contracts import Principal

from app.modules.documents.domain.processing import ProcessingJob
from app.modules.shared.domain.errors import ApplicationError

MAX_ATTEMPTS = 3


class ProcessingRepository(Protocol):
    async def claim(self) -> ProcessingJob | None: ...
    async def succeed(self, job: ProcessingJob) -> None: ...
    async def fail(self, job: ProcessingJob, code: str, retry: bool) -> None: ...


class DocumentProcessor(Protocol):
    async def execute(self, job: ProcessingJob) -> None: ...


class ProcessNextDocument:
    def __init__(self, repository: ProcessingRepository, processor: DocumentProcessor) -> None:
        self.repository = repository
        self.processor = processor

    async def execute(self) -> None:
        job = await self.repository.claim()
        if job is None:
            return
        try:
            await self.processor.execute(job)
        except ApplicationError as error:
            transient = error.code in {"storage_unavailable", "conflict", "throttled"}
            await self.repository.fail(job, error.code, transient and job.attempts < MAX_ATTEMPTS)
        except Exception:
            await self.repository.fail(job, "processing_unavailable", job.attempts < MAX_ATTEMPTS)
        else:
            await self.repository.succeed(job)


class ProcessingJobs(Protocol):
    async def get(self, document_id: UUID) -> ProcessingJob: ...
    async def enqueue(
        self, document_id: UUID, requested_by: UUID, force: bool = False
    ) -> ProcessingJob: ...


class ManageProcessing:
    def __init__(
        self,
        jobs: ProcessingJobs,
        documents: ExtractionRepository,
        access: FamilyAccess,
        registry: ExtractorRegistry,
    ) -> None:
        self.jobs = jobs
        self.documents = documents
        self.access = access
        self.registry = registry

    async def execute(
        self, actor: Principal, document_id: UUID, schedule: bool = False, reindex: bool = False
    ) -> ProcessingJob:
        document = await self.documents.get_visible(actor, document_id)
        await self.access.authorize(
            actor, document.family_id, write=schedule and actor.id != document.owner_id
        )
        if not schedule:
            return await self.jobs.get(document_id)
        if document.status != DocumentStatus.UPLOADED:
            raise ApplicationError("conflict", "Original is not uploaded")
        self.registry.for_mime(document.content_type)
        return await self.jobs.enqueue(document_id, actor.id, force=reindex)
