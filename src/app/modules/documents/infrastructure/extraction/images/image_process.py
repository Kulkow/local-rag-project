"""Decode untrusted images only in a resource-limited child process."""

import json
from pathlib import Path
import resource
import sys

from app.modules.documents.domain.entities import MAX_FILE_BYTES
from app.modules.documents.domain.extraction import ExtractedContent, ExtractionFailure, PageText
from app.modules.documents.domain.images import IMAGE_MEDIA_TYPES, valid_image
from app.modules.documents.infrastructure.extraction.ocr.photo_ocr import recognize_photo
from app.modules.documents.infrastructure.extraction.images.image_preparation import prepare_image


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    result: dict[str, object]
    try:
        data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES or not any(
            valid_image(data, mime) for mime in IMAGE_MEDIA_TYPES
        ):
            raise ExtractionFailure("image_invalid")
        directory = Path(sys.argv[1])
        source = directory / "source.image"
        source.write_bytes(data)
        recognized = recognize_photo(prepare_image(source, directory), directory)
        content = ExtractedContent(
            (PageText(1, recognized.text),),
            ocr_engine=recognized.engine,
            ocr_fallback_reason=recognized.fallback_reason,
        )
        result = {
            "pages": [{"page_number": p.page_number, "text": p.text} for p in content.pages],
            "ocr_engine": content.ocr_engine,
            "ocr_fallback_reason": content.ocr_fallback_reason,
        }
    except ExtractionFailure as error:
        result = {"error": error.code}
    except MemoryError:
        result = {"error": "image_resource_limit"}
    except Exception:
        result = {"error": "image_invalid"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
