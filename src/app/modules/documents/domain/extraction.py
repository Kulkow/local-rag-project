from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID
import unicodedata

from app.modules.documents.domain.entities import validate_error_code
from app.modules.shared.domain.errors import ApplicationError

MAX_PDF_PAGES = 200
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 6 * 1024 * 1024


class ExtractionFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str

    def __post_init__(self) -> None:
        if (
            type(self.page_number) is not int
            or self.page_number < 1
            or not isinstance(self.text, str)
        ):
            raise ExtractionFailure("pdf_invalid")
        text = unicodedata.normalize("NFC", self.text.replace("\r\n", "\n").replace("\r", "\n"))
        text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")
        object.__setattr__(
            self, "text", "\n".join(line.rstrip() for line in text.split("\n")).strip()
        )


@dataclass(frozen=True)
class ExtractedContent:
    pages: tuple[PageText, ...]

    def __post_init__(self) -> None:
        if not self.pages or len(self.pages) > MAX_PDF_PAGES:
            raise ExtractionFailure("pdf_page_limit")
        if any(page.page_number != index for index, page in enumerate(self.pages, 1)):
            raise ExtractionFailure("pdf_invalid")
        if sum(len(page.text.encode("utf-8")) for page in self.pages) > MAX_TEXT_BYTES:
            raise ExtractionFailure("text_limit")
        if not any(page.text for page in self.pages):
            raise ExtractionFailure("no_text")

    @property
    def character_count(self) -> int:
        return sum(len(page.text) for page in self.pages)


class ExtractionStatus(StrEnum):
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    FAILED = "failed"


@dataclass(frozen=True)
class Extraction:
    document_id: UUID
    generation: UUID
    status: ExtractionStatus
    page_count: int = 0
    character_count: int = 0
    error_code: str | None = None
    artifact_key: str | None = None

    def complete(self, page_count: int, character_count: int, artifact_key: str) -> "Extraction":
        self._require_processing()
        if (
            not 1 <= page_count <= MAX_PDF_PAGES
            or character_count <= 0
            or not artifact_key
            or len(artifact_key) > 255
        ):
            raise ApplicationError("invalid", "Invalid extraction result metadata")
        return replace(
            self,
            status=ExtractionStatus.EXTRACTED,
            page_count=page_count,
            character_count=character_count,
            artifact_key=artifact_key,
            error_code=None,
        )

    def fail(self, code: str) -> "Extraction":
        self._require_processing()
        validate_error_code(code)
        return replace(self, status=ExtractionStatus.FAILED, error_code=code)

    def _require_processing(self) -> None:
        if self.status != ExtractionStatus.PROCESSING:
            raise ApplicationError("conflict", "Extraction is not in progress")
