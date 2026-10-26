import asyncio
import json
import sys

from app.modules.documents.domain.extraction import (
    ExtractedContent,
    ExtractionFailure,
    MAX_ARTIFACT_BYTES,
    PageText,
)


class PdfExtractor:
    content_type = "application/pdf"
    name = "pypdf-6.21.2/pages-v1"

    def __init__(self, timeout_seconds: float = 25) -> None:
        self.timeout_seconds = timeout_seconds

    async def extract(self, content: bytes) -> ExtractedContent:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.modules.documents.infrastructure.pdf_process",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                output, _ = await process.communicate(content)
        except (TimeoutError, asyncio.CancelledError) as error:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ExtractionFailure("pdf_timeout") from None
        if process.returncode != 0 or len(output) > MAX_ARTIFACT_BYTES:
            raise ExtractionFailure("pdf_resource_limit")
        try:
            payload = json.loads(output)
            if "error" in payload:
                allowed = {
                    "pdf_invalid",
                    "pdf_encrypted",
                    "pdf_needs_ocr",
                    "pdf_page_limit",
                    "pdf_resource_limit",
                    "text_limit",
                }
                raise ExtractionFailure(
                    payload["error"] if payload["error"] in allowed else "pdf_invalid"
                )
            return ExtractedContent(
                tuple(PageText(page["page_number"], page["text"]) for page in payload["pages"])
            )
        except (ValueError, TypeError, KeyError):
            raise ExtractionFailure("pdf_invalid") from None
