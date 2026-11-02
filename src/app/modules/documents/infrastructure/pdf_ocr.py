"""Bounded local OCR, called only inside the isolated PDF parser process."""

import os
from pathlib import Path
import subprocess

from app.modules.documents.domain.extraction import ExtractionFailure, MAX_TEXT_BYTES


def recognize_page(source: Path, directory: Path, page_number: int) -> str:
    """Render one page at a time, preserving rotation and image placement."""
    image = directory / "page.ppm"
    output = directory / "recognized"
    try:
        _run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-scale-to",
                "2400",
                str(source),
                str(directory / "page"),
            ]
        )
        _run(["tesseract", str(image), str(output), "-l", "rus+eng", "--psm", "3"])
        with output.with_suffix(".txt").open("rb") as stream:
            text = stream.read(MAX_TEXT_BYTES + 1)
        if len(text) > MAX_TEXT_BYTES:
            raise ExtractionFailure("text_limit")
        return text.decode("utf-8")
    except (OSError, UnicodeError):
        raise ExtractionFailure("ocr_failed") from None
    finally:
        image.unlink(missing_ok=True)
        output.with_suffix(".txt").unlink(missing_ok=True)


def _run(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=True,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except FileNotFoundError:
        raise ExtractionFailure("ocr_unavailable") from None
    except subprocess.TimeoutExpired:
        raise ExtractionFailure("ocr_timeout") from None
    except (OSError, subprocess.CalledProcessError):
        raise ExtractionFailure("ocr_failed") from None
