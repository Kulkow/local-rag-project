import hashlib
from io import BytesIO
from pathlib import Path
import tarfile
from unittest.mock import MagicMock

import pytest

from app.modules.documents.infrastructure.extraction.ocr import ocr_models


def archive_bytes(*, unsafe: bool = False) -> bytes:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name in ocr_models.MODEL_FILES:
            entry = tarfile.TarInfo(f"model_infer/{name}")
            entry.size = 4
            if unsafe and name == "inference.json":
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/private/secret"
            archive.addfile(entry, BytesIO(b"test"))
    return output.getvalue()


def response(monkeypatch: pytest.MonkeyPatch, data: bytes) -> MagicMock:
    mocked = MagicMock()
    mocked.return_value.__enter__.return_value.iter_bytes.return_value = [data]
    monkeypatch.setattr(ocr_models.httpx, "stream", mocked)
    return mocked


def test_model_install_is_verified_atomic_and_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = archive_bytes()
    download = response(monkeypatch, data)
    checksum = hashlib.sha256(data).hexdigest()
    ocr_models.install_model("model", checksum, tmp_path)
    ocr_models.install_model("model", checksum, tmp_path)
    assert download.call_count == 1
    assert (tmp_path / "model/inference.json").read_bytes() == b"test"
    assert (tmp_path / "model").stat().st_mode & 0o777 == 0o755
    assert sorted(item.name for item in tmp_path.iterdir()) == ["model"]


def test_bad_checksum_never_publishes_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response(monkeypatch, archive_bytes())
    with pytest.raises(RuntimeError, match="checksum"):
        ocr_models.install_model("model", "0" * 64, tmp_path)
    assert not list(tmp_path.iterdir())


def test_symlinks_are_not_extracted_even_in_verified_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = archive_bytes(unsafe=True)
    response(monkeypatch, data)
    with pytest.raises(RuntimeError, match="Invalid model archive"):
        ocr_models.install_model("model", hashlib.sha256(data).hexdigest(), tmp_path)
    assert not list(tmp_path.iterdir())
