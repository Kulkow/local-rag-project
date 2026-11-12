import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from app.modules.documents.domain.extraction import ExtractionFailure, MAX_TEXT_BYTES
from app.modules.documents.infrastructure.extraction.ocr import photo_ocr
from app.modules.documents.infrastructure.extraction.ocr.paddle_process import recognize


def test_primary_success_does_not_call_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        (tmp_path / "paddle.json").write_text(json.dumps({"text": "Русский документ"}))
        return subprocess.CompletedProcess([], 0)

    fallback = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(photo_ocr, "recognize_image", fallback)
    result = photo_ocr.recognize_photo(tmp_path / "photo.png", tmp_path)
    assert result.text == "Русский документ" and result.engine == "paddleocr"
    assert result.fallback_reason is None
    fallback.assert_not_called()


@pytest.mark.parametrize(
    "reason", ["paddle_models_missing", "paddle_low_confidence", "paddle_no_text", "paddle_failed"]
)
def test_primary_error_uses_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        (tmp_path / "paddle.json").write_text(json.dumps({"error": reason}))
        return subprocess.CompletedProcess([], 0)

    fallback = Mock(return_value="Резервная расшифровка")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(photo_ocr, "recognize_image", fallback)
    result = photo_ocr.recognize_photo(tmp_path / "photo.png", tmp_path)
    assert result.engine == "tesseract" and result.fallback_reason == reason
    assert result.text == "Резервная расшифровка"
    fallback.assert_called_once_with(tmp_path / "photo.png", tmp_path, photo=True)


@pytest.mark.parametrize(
    "failure,reason",
    [
        (subprocess.TimeoutExpired("paddle", 55), "paddle_timeout"),
        (OSError("private error details"), "paddle_failed"),
    ],
)
def test_timeout_and_native_failure_use_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception, reason: str
) -> None:
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    monkeypatch.setattr(photo_ocr, "recognize_image", Mock(return_value="Результат"))
    result = photo_ocr.recognize_photo(tmp_path / "photo.png", tmp_path)
    assert result.fallback_reason == reason


def test_native_crash_uses_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], -11)))
    monkeypatch.setattr(photo_ocr, "recognize_image", Mock(return_value="Результат"))
    assert photo_ocr.recognize_photo(tmp_path / "photo.png", tmp_path).engine == "tesseract"


def test_fallback_error_remains_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 1)))
    monkeypatch.setattr(
        photo_ocr, "recognize_image", Mock(side_effect=ExtractionFailure("ocr_timeout"))
    )
    with pytest.raises(ExtractionFailure, match="ocr_timeout"):
        photo_ocr.recognize_photo(tmp_path / "photo.png", tmp_path)


def test_result_limit_is_not_bypassed_by_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        (tmp_path / "paddle.json").write_bytes(b"x" * (MAX_TEXT_BYTES + 4097))
        return subprocess.CompletedProcess([], 0)

    fallback = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(photo_ocr, "recognize_image", fallback)
    with pytest.raises(ExtractionFailure, match="text_limit"):
        photo_ocr.recognize_photo(tmp_path / "photo.png", tmp_path)
    fallback.assert_not_called()


@pytest.mark.parametrize(
    "texts,scores,error",
    [
        ([], [], "paddle_no_text"),
        (["Текст"], [0.2], "paddle_low_confidence"),
        (["Текст"], [float("nan")], "paddle_failed"),
        (["Текст"], [], "paddle_failed"),
    ],
)
def test_unreliable_primary_results_are_rejected(
    texts: list[str], scores: list[float], error: str
) -> None:
    engine = Mock()
    engine.predict.return_value = [{"rec_texts": texts, "rec_scores": scores}]
    assert recognize(engine, Path("photo.png")) == {"error": error}


def test_primary_preserves_reading_order_and_mixed_languages() -> None:
    engine = Mock()
    engine.predict.return_value = [
        {"rec_texts": ["Русский текст", "Invoice 123"], "rec_scores": [0.99, 0.95]}
    ]
    assert recognize(engine, Path("photo.png")) == {"text": "Русский текст\nInvoice 123"}


def test_mixed_script_homoglyphs_request_another_engine() -> None:
    engine = Mock()
    engine.predict.return_value = [{"rec_texts": ["Invоісе"], "rec_scores": [0.99]}]
    assert recognize(engine, Path("photo.png")) == {"error": "paddle_mixed_script"}
