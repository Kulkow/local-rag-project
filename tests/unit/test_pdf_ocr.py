from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from app.modules.documents.domain.extraction import ExtractionFailure, MAX_TEXT_BYTES
from app.modules.documents.infrastructure.pdf_ocr import recognize_page


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FileNotFoundError("private path"), "ocr_unavailable"),
        (subprocess.TimeoutExpired("private command", 20), "ocr_timeout"),
        (subprocess.CalledProcessError(1, "private command"), "ocr_failed"),
    ],
)
def test_ocr_errors_are_safe_and_clean_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception, code: str
) -> None:
    (tmp_path / "page.ppm").write_bytes(b"private pixels")
    (tmp_path / "recognized.txt").write_text("private text")
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(ExtractionFailure) as error:
        recognize_page(tmp_path / "source.pdf", tmp_path, 1)
    assert str(error.value) == code
    assert not (tmp_path / "page.ppm").exists()
    assert not (tmp_path / "recognized.txt").exists()


def test_ocr_text_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "recognized.txt").write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    monkeypatch.setattr(subprocess, "run", Mock())
    with pytest.raises(ExtractionFailure, match="text_limit"):
        recognize_page(tmp_path / "source.pdf", tmp_path, 1)
    assert not (tmp_path / "recognized.txt").exists()
