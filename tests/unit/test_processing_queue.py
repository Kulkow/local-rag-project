"""Durable processing queue uses bounded retries without document content in jobs."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.documents.application.processing import ProcessNextDocument
from app.modules.documents.domain.processing import ProcessingJob, ProcessingStatus
from app.modules.shared.domain.errors import ApplicationError


def job(attempts: int = 1) -> ProcessingJob:
    return ProcessingJob(uuid4(), uuid4(), uuid4(), ProcessingStatus.PROCESSING, attempts)


async def test_empty_queue_does_not_call_processor() -> None:
    repository, processor = AsyncMock(), AsyncMock()
    repository.claim.return_value = None
    await ProcessNextDocument(repository, processor).execute()
    processor.execute.assert_not_awaited()


async def test_success_finishes_claimed_generation() -> None:
    repository, processor = AsyncMock(), AsyncMock()
    run = job()
    repository.claim.return_value = run
    await ProcessNextDocument(repository, processor).execute()
    processor.execute.assert_awaited_once_with(run)
    repository.succeed.assert_awaited_once_with(run)


@pytest.mark.parametrize("attempts,retry", [(1, True), (2, True), (3, False)])
async def test_storage_failures_have_bounded_retries(attempts: int, retry: bool) -> None:
    repository, processor = AsyncMock(), AsyncMock()
    run = job(attempts)
    repository.claim.return_value = run
    processor.execute.side_effect = ApplicationError("storage_unavailable", "secret SDK detail")
    await ProcessNextDocument(repository, processor).execute()
    repository.fail.assert_awaited_once_with(run, "storage_unavailable", retry)


@pytest.mark.parametrize("code", ["invalid", "forbidden", "not_found", "unsupported_media"])
async def test_permanent_failures_are_not_retried(code: str) -> None:
    repository, processor = AsyncMock(), AsyncMock()
    run = job()
    repository.claim.return_value = run
    processor.execute.side_effect = ApplicationError(code, "sensitive text")
    await ProcessNextDocument(repository, processor).execute()
    repository.fail.assert_awaited_once_with(run, code, False)


async def test_unknown_error_is_sanitized() -> None:
    repository, processor = AsyncMock(), AsyncMock()
    run = job()
    repository.claim.return_value = run
    processor.execute.side_effect = RuntimeError("document text")
    await ProcessNextDocument(repository, processor).execute()
    repository.fail.assert_awaited_once_with(run, "processing_unavailable", True)


async def test_worker_rechecks_active_requester_before_accessing_original() -> None:
    from unittest.mock import MagicMock, patch
    from app.modules.documents.infrastructure.processing_worker import ExtractQueuedDocument

    factory = MagicMock()
    actor_repository = AsyncMock()
    actor_repository.active_principal.return_value = None
    processor = ExtractQueuedDocument(factory, AsyncMock(), AsyncMock())
    processor.use_case = AsyncMock()
    with patch(
        "app.modules.documents.infrastructure.processing_worker.SqlIdentityRepository",
        return_value=actor_repository,
    ):
        with pytest.raises(ApplicationError) as error:
            await processor.execute(job())
    assert error.value.code == "forbidden"
    processor.use_case.execute.assert_not_awaited()
