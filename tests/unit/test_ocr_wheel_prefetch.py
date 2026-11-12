import hashlib
from pathlib import Path
import runpy
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prefetch_ocr_wheels.py"


def test_range_assembly_verifies_hash_and_reuses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(SCRIPT))
    download = module["download"]
    data = b"synthetic locked wheel" * 100

    def fetch(url: str, start: int, end: int, target: Path) -> None:
        target.write_bytes(data[start : end + 1])

    reader = Mock(side_effect=fetch)
    monkeypatch.setitem(download.__globals__, "fetch_part", reader)
    wheel = {
        "url": "https://example.test/test.whl",
        "size": len(data),
        "hash": "sha256:" + hashlib.sha256(data).hexdigest(),
    }
    download(wheel, tmp_path)
    assert (tmp_path / "test.whl").read_bytes() == data
    assert reader.call_count == 8
    download(wheel, tmp_path)
    assert reader.call_count == 8
    assert sorted(path.name for path in tmp_path.iterdir()) == ["test.whl"]


def test_corrupt_range_is_never_published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(SCRIPT))
    download = module["download"]

    def fetch(url: str, start: int, end: int, target: Path) -> None:
        target.write_bytes(b"corrupt")

    monkeypatch.setitem(download.__globals__, "fetch_part", fetch)
    with pytest.raises(RuntimeError, match="checksum"):
        download(
            {"url": "https://example.test/test.whl", "size": 80, "hash": "sha256:" + "0" * 64},
            tmp_path,
        )
    assert not list(tmp_path.iterdir())
