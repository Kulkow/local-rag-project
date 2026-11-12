"""Paddle inference child. Local models only; no document text in stdout/logging."""

import json
import logging
import math
import os
from pathlib import Path
import resource
import re
import sys
from typing import Any

from app.modules.documents.domain.extraction import MAX_TEXT_BYTES

DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODEL = "eslav_PP-OCRv5_mobile_rec"
MIN_CONFIDENCE = 0.65  # Initial operating default, not a measured quality guarantee.


def model_root() -> Path:
    return Path(os.environ.get("OCR_MODELS_DIR", "/opt/ocr-models"))


def create_engine() -> Any:
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=DETECTION_MODEL,
        text_detection_model_dir=str(model_root() / DETECTION_MODEL),
        text_recognition_model_name=RECOGNITION_MODEL,
        text_recognition_model_dir=str(model_root() / RECOGNITION_MODEL),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        cpu_threads=1,
        enable_mkldnn=False,
        text_det_limit_side_len=1280,
        text_det_limit_type="max",
        text_recognition_batch_size=4,
        text_rec_score_thresh=0.0,
    )


def recognize(engine: Any, image: Path) -> dict[str, str]:
    lines: list[str] = []
    confidence_sum = 0.0
    character_count = 0
    byte_count = 0
    for result in engine.predict(str(image)):
        texts, scores = result["rec_texts"], result["rec_scores"]
        if len(texts) != len(scores):
            return {"error": "paddle_failed"}
        for text, score in zip(texts, scores, strict=True):
            if not isinstance(text, str) or not math.isfinite(float(score)):
                return {"error": "paddle_failed"}
            text = text.strip()
            if not text:
                continue
            byte_count += len(text.encode("utf-8")) + 1
            if byte_count > MAX_TEXT_BYTES:
                return {"error": "text_limit"}
            # Script mixing inside one token often indicates Cyrillic/Latin homoglyph errors.
            # Do not invent spelling corrections; ask the bilingual fallback to read the image.
            if any(
                re.search(r"[A-Za-z]", token) and re.search(r"[\u0400-\u04ff]", token)
                for token in re.findall(r"[^\W\d_]+", text)
            ):
                return {"error": "paddle_mixed_script"}
            lines.append(text)
            confidence_sum += max(0.0, min(1.0, float(score))) * len(text)
            character_count += len(text)
    if not character_count:
        return {"error": "paddle_no_text"}
    if confidence_sum / character_count < MIN_CONFIDENCE:
        return {"error": "paddle_low_confidence"}
    return {"text": "\n".join(lines)}


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    logging.disable(logging.CRITICAL)
    result = {"error": "paddle_models_missing"}
    if all(
        (model_root() / model / "inference.yml").is_file()
        for model in (DETECTION_MODEL, RECOGNITION_MODEL)
    ):
        try:
            result = recognize(create_engine(), Path(sys.argv[1]))
        except Exception:
            result = {"error": "paddle_failed"}
    # ASCII JSON bounds apply even when native libraries emit warnings to stdout/stderr.
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
