"""Isolated parser process: stdin PDF -> bounded JSON; never emits document logs."""

import io
import json
import logging
import resource
import sys

from app.modules.documents.domain.entities import MAX_FILE_BYTES
from app.modules.documents.domain.extraction import (
    ExtractedContent,
    ExtractionFailure,
    MAX_PDF_PAGES,
    MAX_TEXT_BYTES,
    PageText,
)


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    logging.disable(logging.CRITICAL)
    result: dict[str, object]
    try:
        from pypdf import PdfReader
        import pypdf.filters

        pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH = 16 * 1024 * 1024
        pypdf.filters.JBIG2_MAX_OUTPUT_LENGTH = 16 * 1024 * 1024
        data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if not data or len(data) > MAX_FILE_BYTES:
            raise ExtractionFailure("pdf_invalid")
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ExtractionFailure("pdf_encrypted")
        if not 0 < len(reader.pages) <= MAX_PDF_PAGES:
            raise ExtractionFailure("pdf_page_limit")
        pages = []
        total_bytes = 0
        for number, page in enumerate(reader.pages, 1):
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > 16 * 1024 * 1024:
                raise ExtractionFailure("pdf_resource_limit")
            text = PageText(number, page.extract_text() or "")
            total_bytes += len(text.text.encode("utf-8"))
            if total_bytes > MAX_TEXT_BYTES:
                raise ExtractionFailure("text_limit")
            pages.append(text)
        content = ExtractedContent(tuple(pages))
        result = {"pages": [{"page_number": p.page_number, "text": p.text} for p in content.pages]}
    except ExtractionFailure as error:
        result = {"error": "pdf_needs_ocr" if error.code == "no_text" else error.code}
    except (MemoryError, RecursionError):
        result = {"error": "pdf_resource_limit"}
    except Exception:
        result = {"error": "pdf_invalid"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
