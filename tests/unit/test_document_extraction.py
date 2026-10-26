"""TDD contract: pluggable extractors and durable, authorized PDF extraction."""

import hashlib
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.documents.application.extraction import ExtractDocument, ExtractorRegistry
from app.modules.documents.domain.extraction import (
    ExtractedContent,
    PageText,
    Extraction,
    ExtractionStatus,
)
from app.modules.documents.domain.entities import Document, DocumentStatus, Visibility
from app.modules.identity.application.contracts import Principal, UserRole
from app.modules.shared.domain.errors import ApplicationError


class PdfFake:
    content_type = "application/pdf"
    name = "fake-pdf"

    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, content: bytes) -> ExtractedContent:
        self.calls += 1
        return ExtractedContent((PageText(1, "Synthetic evidence"), PageText(2, "")))


class RepositoryFake:
    def __init__(self, document: Document) -> None:
        self.document = document
        self.run: Extraction | None = None

    async def get_visible(self, actor: Principal, document_id: object) -> Document:
        return self.document

    async def claim(self, document: Document) -> tuple[Extraction, bool]:
        if self.run and self.run.status == ExtractionStatus.EXTRACTED:
            return self.run, False
        self.run = Extraction(document.id, uuid4(), ExtractionStatus.PROCESSING)
        return self.run, True

    async def complete(
        self,
        run: Extraction,
        page_count: int,
        character_count: int,
        artifact_key: str,
        title: str | None = None,
    ) -> Extraction:
        self.run = replace(
            run,
            status=ExtractionStatus.EXTRACTED,
            page_count=page_count,
            character_count=character_count,
            artifact_key=artifact_key,
        )
        self.document = replace(self.document, title=title)
        return self.run

    async def set_title(self, run: Extraction, title: str | None) -> None:
        self.document = replace(self.document, title=title)

    async def fail(self, run: Extraction, code: str) -> None:
        self.run = replace(run, status=ExtractionStatus.FAILED, error_code=code)


@pytest.fixture
def setup() -> tuple:
    content = b"synthetic PDF bytes"
    actor = Principal(uuid4(), "synthetic", UserRole.MANAGER, uuid4())
    document = Document(
        uuid4(),
        uuid4(),
        actor.id,
        "guide.pdf",
        "application/pdf",
        len(content),
        hashlib.sha256(content).hexdigest(),
        "original",
        Visibility.PRIVATE,
        DocumentStatus.UPLOADED,
    )
    repository = RepositoryFake(document)
    storage, access = AsyncMock(), AsyncMock()
    storage.get.return_value = content
    extractor = PdfFake()
    return (
        ExtractDocument(repository, storage, ExtractorRegistry([extractor]), access),
        repository,
        storage,
        access,
        extractor,
        actor,
    )


async def test_extract_pdf_persists_pages_and_is_idempotent(setup: tuple) -> None:
    use_case, repository, storage, access, extractor, actor = setup
    result = await use_case.execute(actor, repository.document.id)
    assert result.status == ExtractionStatus.EXTRACTED and result.page_count == 2
    access.authorize.assert_awaited_once_with(actor, repository.document.family_id, write=False)
    storage.put.assert_awaited_once()
    artifact = storage.put.call_args.args[1]
    assert b"Synthetic evidence" in artifact and b'"page_number": 2' in artifact
    assert (await use_case.execute(actor, repository.document.id)).generation == result.generation
    assert extractor.calls == 1


async def test_permission_failure_never_reads_original(setup: tuple) -> None:
    use_case, repository, storage, access, _, actor = setup
    access.authorize.side_effect = ApplicationError("not_found", "Family not found")
    with pytest.raises(ApplicationError):
        await use_case.execute(actor, repository.document.id)
    storage.get.assert_not_awaited()
    assert repository.run is None


async def test_unregistered_format_is_not_claimed(setup: tuple) -> None:
    use_case, repository, storage, _, _, actor = setup
    repository.document = replace(repository.document, content_type="text/html")
    with pytest.raises(ApplicationError) as error:
        await use_case.execute(actor, repository.document.id)
    assert error.value.code == "unsupported_media"
    assert repository.run is None
    storage.get.assert_not_awaited()


async def test_original_checksum_is_checked_before_extraction(setup: tuple) -> None:
    use_case, repository, storage, _, extractor, actor = setup
    storage.get.return_value = b"replaced original"
    with pytest.raises(ApplicationError):
        await use_case.execute(actor, repository.document.id)
    assert extractor.calls == 0
    assert repository.run is not None and repository.run.status == ExtractionStatus.FAILED
    assert repository.run.error_code == "source_checksum_mismatch"


async def test_storage_failure_records_error_and_cleans_artifact(setup: tuple) -> None:
    use_case, repository, storage, _, _, actor = setup
    storage.put.side_effect = OSError("sensitive SDK details")
    with pytest.raises(ApplicationError) as error:
        await use_case.execute(actor, repository.document.id)
    assert "sensitive" not in str(error.value)
    assert repository.run is not None and repository.run.status == ExtractionStatus.FAILED
    storage.delete.assert_awaited_once()


def test_registry_rejects_duplicate_mime_handlers() -> None:
    with pytest.raises(ValueError):
        ExtractorRegistry([PdfFake(), PdfFake()])


async def test_member_owner_can_process_their_upload(setup: tuple) -> None:
    use_case, repository, _, access, _, actor = setup
    member = replace(actor, role=UserRole.MEMBER)
    result = await use_case.execute(member, repository.document.id)
    assert result.status == ExtractionStatus.EXTRACTED
    access.authorize.assert_awaited_once_with(member, repository.document.family_id, write=False)
