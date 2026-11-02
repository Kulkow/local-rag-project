import asyncio
import json
import os
import signal
import sys
from tempfile import TemporaryDirectory

from app.modules.documents.domain.extraction import (
    ExtractedContent,
    ExtractionFailure,
    MAX_ARTIFACT_BYTES,
    PageText,
)


class PdfExtractor:
    content_type = "application/pdf"
    name = "pypdf-6.21.2/tesseract-rus+eng/pages-v2"

    def __init__(self, timeout_seconds: float = 100) -> None:
        self.timeout_seconds = timeout_seconds

    async def extract(self, content: bytes) -> ExtractedContent:
        # The parent owns cleanup even when the parser/OCR process is killed.
        with TemporaryDirectory(prefix="rag-ocr-") as directory:
            return await self._extract(content, directory)

    async def _extract(self, content: bytes, directory: str) -> ExtractedContent:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.modules.documents.infrastructure.pdf_process",
            directory,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                output, _ = await process.communicate(content)
        except (TimeoutError, asyncio.CancelledError) as error:
            self._kill_group(process.pid)
            await process.communicate()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise ExtractionFailure("pdf_timeout") from None
        finally:
            # Also stop descendants if the parser crashes before waiting for them.
            self._kill_group(process.pid)
        if process.returncode != 0 or len(output) > MAX_ARTIFACT_BYTES:
            raise ExtractionFailure("pdf_resource_limit")
        try:
            payload = json.loads(output)
            if "error" in payload:
                allowed = {
                    "pdf_invalid",
                    "pdf_encrypted",
                    "no_text",
                    "ocr_unavailable",
                    "ocr_failed",
                    "ocr_timeout",
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

    @staticmethod
    def _kill_group(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
