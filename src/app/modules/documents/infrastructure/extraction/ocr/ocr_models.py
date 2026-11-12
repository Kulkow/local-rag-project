"""Explicit, checksum-pinned model initialization; never called during ingestion."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from tempfile import TemporaryDirectory
import time

import httpx

from app.modules.documents.infrastructure.extraction.ocr.paddle_process import (
    DETECTION_MODEL,
    RECOGNITION_MODEL,
    model_root,
)

MODEL_ARCHIVES = {
    DETECTION_MODEL: "50446e5d01ac2a73d5319c89513281f6578414c888c602f9af13f93feefffc58",
    RECOGNITION_MODEL: "b9f70da0ca2bbc4d4cb7ba406a2d023061178437d6a930f07c8ca18c6c591839",
}
BASE_URL = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"
MODEL_FILES = ("inference.yml", "inference.json", "inference.pdiparams")
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


def install_model(name: str, checksum: str, root: Path) -> None:
    target = root / name
    marker = target / "archive.sha256"
    if (
        marker.is_file()
        and marker.read_text().strip() == checksum
        and all((target / filename).is_file() for filename in MODEL_FILES)
    ):
        return
    if target.exists():
        raise RuntimeError(f"Model directory is incomplete: {name}; remove it before retrying")
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".download-", dir=root) as temporary:
        stage = Path(temporary)
        archive = stage / "model.tar"
        digest = hashlib.sha256()
        count = 0
        deadline = time.monotonic() + 120
        with (
            httpx.stream(
                "GET", f"{BASE_URL}/{name}_infer.tar", timeout=30, follow_redirects=False
            ) as response,
            archive.open("wb") as stream,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes():
                count += len(chunk)
                if count > MAX_ARCHIVE_BYTES or time.monotonic() > deadline:
                    raise RuntimeError("Model download limit exceeded")
                digest.update(chunk)
                stream.write(chunk)
        if digest.hexdigest() != checksum:
            raise RuntimeError("Model checksum mismatch")
        unpacked = stage / "model"
        unpacked.mkdir(mode=0o755)
        with tarfile.open(archive) as source:
            for filename in MODEL_FILES:
                member = source.getmember(f"{name}_infer/{filename}")
                if not member.isfile() or member.size > MAX_ARCHIVE_BYTES:
                    raise RuntimeError("Invalid model archive")
                contents = source.extractfile(member)
                if contents is None:
                    raise RuntimeError("Missing model file")
                with contents, (unpacked / filename).open("wb") as destination:
                    shutil.copyfileobj(contents, destination)
                (unpacked / filename).chmod(0o644)
        (unpacked / "archive.sha256").write_text(checksum + "\n")
        (unpacked / "archive.sha256").chmod(0o644)
        unpacked.rename(target)


def main() -> None:
    for name, checksum in MODEL_ARCHIVES.items():
        install_model(name, checksum, model_root())
    print(json.dumps({"ocr_models": "ready", "models": list(MODEL_ARCHIVES)}))


if __name__ == "__main__":
    main()
