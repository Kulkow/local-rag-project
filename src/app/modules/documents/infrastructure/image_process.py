"""Decode untrusted images only in a resource-limited child process."""

import json
from pathlib import Path
import resource
import sys

from app.modules.documents.domain.entities import MAX_FILE_BYTES
from app.modules.documents.domain.extraction import ExtractedContent, ExtractionFailure, PageText
from app.modules.documents.domain.images import IMAGE_MEDIA_TYPES, valid_image
from app.modules.documents.infrastructure.pdf_ocr import recognize_image


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
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
        content = ExtractedContent((PageText(1, recognize_image(source, directory)),))
        result = {"pages": [{"page_number": p.page_number, "text": p.text} for p in content.pages]}
    except ExtractionFailure as error:
        result = {"error": error.code}
    except MemoryError:
        result = {"error": "image_resource_limit"}
    except Exception:
        result = {"error": "image_invalid"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
