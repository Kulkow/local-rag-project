"""OpenCV-prepared photo -> bounded Paddle child -> local Tesseract fallback."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

from app.modules.documents.domain.extraction import ExtractionFailure, MAX_TEXT_BYTES
from app.modules.documents.infrastructure.extraction.ocr.pdf_ocr import recognize_image


@dataclass(frozen=True)
class PhotoRecognition:
    text: str
    engine: str
    fallback_reason: str | None = None


def recognize_photo(image: Path, directory: Path) -> PhotoRecognition:
    reason = "paddle_failed"
    try:
        output = directory / "paddle.json"
        output.unlink(missing_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.modules.documents.infrastructure.extraction.ocr.paddle_process",
                str(image),
                str(output),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=55,
            check=False,
            env={
                **os.environ,
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "HF_HUB_OFFLINE": "1",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                "DISABLE_MODEL_SOURCE_CHECK": "True",
            },
        )
        if completed.returncode == 0 and output.exists():
            with output.open("rb") as stream:
                raw = stream.read(MAX_TEXT_BYTES + 4097)
            if len(raw) > MAX_TEXT_BYTES + 4096:
                raise ExtractionFailure("text_limit")
            result = json.loads(raw)
            text = result.get("text")
            if isinstance(text, str) and text.strip():
                if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
                    raise ExtractionFailure("text_limit")
                return PhotoRecognition(text, "paddleocr")
            candidate = result.get("error")
            if candidate == "text_limit":
                raise ExtractionFailure("text_limit")
            if candidate in {
                "paddle_models_missing",
                "paddle_low_confidence",
                "paddle_no_text",
                "paddle_mixed_script",
            }:
                reason = candidate
    except subprocess.TimeoutExpired:
        reason = "paddle_timeout"
    except (OSError, ValueError, TypeError, AttributeError):
        reason = "paddle_failed"
    return PhotoRecognition(recognize_image(image, directory, photo=True), "tesseract", reason)
