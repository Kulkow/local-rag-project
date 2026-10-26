"""Upload metadata and policies. No parser output is trusted as model instructions."""

import hashlib
import io
import re
import stat
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID

from app.modules.shared.domain.errors import ApplicationError

MAX_FILE_BYTES = 10 * 1024 * 1024
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
}


class Visibility(StrEnum):
    PRIVATE = "private"
    FAMILY = "family"


class DocumentStatus(StrEnum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    UPLOAD_FAILED = "upload_failed"


@dataclass(frozen=True)
class Document:
    id: UUID
    family_id: UUID
    owner_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    checksum: str
    object_key: str
    visibility: Visibility
    status: DocumentStatus = DocumentStatus.UPLOADING
    error_code: str | None = None
    created_at: datetime | None = None
    title: str | None = None

    def complete_upload(self) -> "Document":
        self._require_uploading()
        return replace(self, status=DocumentStatus.UPLOADED, error_code=None)

    def fail_upload(self, code: str) -> "Document":
        self._require_uploading()
        validate_error_code(code)
        return replace(self, status=DocumentStatus.UPLOAD_FAILED, error_code=code)

    def retry_upload(self) -> "Document":
        if self.status != DocumentStatus.UPLOAD_FAILED:
            raise ApplicationError("conflict", "Only a failed upload can be retried")
        return replace(self, status=DocumentStatus.UPLOADING, error_code=None)

    def _require_uploading(self) -> None:
        if self.status != DocumentStatus.UPLOADING:
            raise ApplicationError("conflict", "Upload is not in progress")


def validate_error_code(code: str) -> None:
    if not code or len(code) > 50:
        raise ApplicationError("invalid", "Error code must contain 1 to 50 characters")


def validate_file(filename: str, content_type: str, content: bytes) -> tuple[str, str]:
    if (
        not filename
        or len(filename) > 255
        or any(ord(c) < 32 or ord(c) == 127 for c in filename)
        or "/" in filename
        or "\\" in filename
    ):
        raise ApplicationError("invalid", "Invalid filename")
    if len(content) > MAX_FILE_BYTES:
        raise ApplicationError("payload_too_large", "File exceeds the 10 MiB limit")
    if not content:
        raise ApplicationError("invalid", "File is empty")
    extension = PurePosixPath(filename).suffix.lower()
    expected = MEDIA_TYPES.get(extension)
    declared = content_type.split(";", 1)[0].strip().lower()
    if expected is None or declared not in (expected, "application/octet-stream"):
        raise ApplicationError("unsupported_media", "Allowed file types: PDF, DOCX and HTML")
    valid = False
    if extension == ".pdf":
        valid = (
            bool(re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\s|$)", content[:16]))
            and b"%%EOF" in content[-1024:]
        )
    elif extension in (".html", ".htm"):
        try:
            text = content.decode("utf-8-sig")
            valid = "\x00" not in text and bool(
                re.search(r"<!doctype\s+html\b|<html\b|<body\b", text[:4096], re.IGNORECASE)
            )
        except UnicodeDecodeError:
            valid = False
    elif extension == ".docx":
        valid = valid_docx(content)
    if not valid:
        raise ApplicationError(
            "unsupported_media", "File content does not match a supported format"
        )
    return expected, hashlib.sha256(content).hexdigest()


def valid_docx(content: bytes) -> bool:
    try:
        end = content.rfind(b"PK\x05\x06", max(0, len(content) - 65557))
        if end < 0 or len(content) - end < 22:
            return False
        if (
            int.from_bytes(content[end + 10 : end + 12], "little") > 1000
            or int.from_bytes(content[end + 12 : end + 16], "little") > 512 * 1024
        ):
            return False
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
                return False
            names = set()
            for item in entries:
                path = PurePosixPath(item.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in item.filename
                    or item.flag_bits & 1
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    return False
                if item.file_size > max(item.compress_size, 1) * 200:
                    return False
                if item.filename in names:
                    return False
                names.add(item.filename)
            # Container validation only; XML extraction belongs to the later ingestion stage.
            return {"[Content_Types].xml", "word/document.xml"}.issubset(names)
    except (zipfile.BadZipFile, ValueError, OSError):
        return False
