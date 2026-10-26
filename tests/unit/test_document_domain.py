"""Document lifecycle rules are independent of persistence and HTTP."""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.documents.domain.entities import Document, DocumentStatus, Visibility
from app.modules.documents.domain.extraction import Extraction, ExtractionStatus
from app.modules.shared.domain.errors import ApplicationError


def document() -> Document:
    return Document(
        uuid4(),
        uuid4(),
        uuid4(),
        "guide.pdf",
        "application/pdf",
        10,
        "a" * 64,
        "original",
        Visibility.PRIVATE,
    )


def test_upload_transitions_preserve_identity_and_metadata() -> None:
    original = document()
    completed = original.complete_upload()
    assert completed == replace(original, status=DocumentStatus.UPLOADED)
    assert original.status == DocumentStatus.UPLOADING
    failed = original.fail_upload("storage_unavailable")
    assert failed.status == DocumentStatus.UPLOAD_FAILED
    assert failed.error_code == "storage_unavailable"
    assert failed.retry_upload() == original


@pytest.mark.parametrize("status", [DocumentStatus.UPLOADED, DocumentStatus.UPLOAD_FAILED])
def test_upload_cannot_finish_twice(status: DocumentStatus) -> None:
    existing = replace(document(), status=status)
    with pytest.raises(ApplicationError, match="in progress"):
        existing.complete_upload()
    with pytest.raises(ApplicationError, match="in progress"):
        existing.fail_upload("storage_unavailable")


def test_retry_requires_failed_upload() -> None:
    with pytest.raises(ApplicationError):
        document().retry_upload()
    with pytest.raises(ApplicationError):
        document().complete_upload().retry_upload()


def test_extraction_completion_and_failure() -> None:
    run = Extraction(uuid4(), uuid4(), ExtractionStatus.PROCESSING)
    result = run.complete(2, 100, "extracted/result.json")
    assert result.status == ExtractionStatus.EXTRACTED
    assert (result.page_count, result.character_count, result.artifact_key) == (
        2,
        100,
        "extracted/result.json",
    )
    assert result.document_id == run.document_id and result.generation == run.generation
    assert run.status == ExtractionStatus.PROCESSING
    failed = run.fail("pdf_invalid")
    assert failed.status == ExtractionStatus.FAILED and failed.error_code == "pdf_invalid"
    with pytest.raises(ApplicationError):
        result.fail("pdf_invalid")
    with pytest.raises(ApplicationError):
        failed.complete(1, 1, "artifact")


@pytest.mark.parametrize(
    "pages,characters,key",
    [(0, 1, "a"), (201, 1, "a"), (1, 0, "a"), (1, -1, "a"), (1, 1, ""), (1, 1, "a" * 256)],
)
def test_extraction_rejects_invalid_completion(pages: int, characters: int, key: str) -> None:
    run = Extraction(uuid4(), uuid4(), ExtractionStatus.PROCESSING)
    with pytest.raises(ApplicationError):
        run.complete(pages, characters, key)


@pytest.mark.parametrize("code", ["", "x" * 51])
def test_failure_codes_match_storage_limits(code: str) -> None:
    with pytest.raises(ApplicationError):
        document().fail_upload(code)
    with pytest.raises(ApplicationError):
        Extraction(uuid4(), uuid4(), ExtractionStatus.PROCESSING).fail(code)
