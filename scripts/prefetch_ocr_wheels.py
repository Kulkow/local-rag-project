"""Prefetch large locked CPU wheels in bounded HTTP ranges for Docker builds.

Downloads only registry artifacts selected from uv.lock and verifies their locked SHA-256.
Installing by package name from --find-links keeps normal registry distribution metadata.
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
import tomllib
from urllib.request import Request, urlopen

PACKAGES = {"paddlepaddle", "opencv-contrib-python"}
MAX_WHEEL_BYTES = 256 * 1024 * 1024
PARTS = 8


def fetch_part(url: str, start: int, end: int, target: Path) -> None:
    request = Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urlopen(request, timeout=60) as response, target.open("wb") as output:
        if response.status != 206:
            raise RuntimeError("Registry does not support ranged wheel downloads")
        remaining = end - start + 1
        while remaining:
            chunk = response.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError("Incomplete wheel range")
            output.write(chunk)
            remaining -= len(chunk)


def download(wheel: dict[str, object], directory: Path) -> None:
    url, checksum, size = str(wheel["url"]), str(wheel["hash"]), int(str(wheel["size"]))
    if not 0 < size <= MAX_WHEEL_BYTES:
        raise RuntimeError("Wheel exceeds prefetch limit")
    target = directory / url.rsplit("/", 1)[1]
    if target.exists() and "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
        return
    with TemporaryDirectory(dir=directory) as temporary:
        stage = Path(temporary)
        width = (size + PARTS - 1) // PARTS
        with ThreadPoolExecutor(max_workers=PARTS) as executor:
            tasks = [
                executor.submit(
                    fetch_part, url, start, min(size - 1, start + width - 1), stage / str(index)
                )
                for index, start in enumerate(range(0, size, width))
            ]
            for task in tasks:
                task.result()
        assembled = stage / "wheel"
        digest = hashlib.sha256()
        with assembled.open("wb") as output:
            for index in range(len(tasks)):
                with (stage / str(index)).open("rb") as part:
                    while chunk := part.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
        if "sha256:" + digest.hexdigest() != checksum:
            raise RuntimeError("Locked wheel checksum mismatch")
        assembled.replace(target)
    print(f"Verified locked wheel: {target.name}", flush=True)


def main() -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("CPU OCR image currently supports Linux x86_64")
    directory = Path("/root/.cache/ocr-wheels")
    directory.mkdir(parents=True, exist_ok=True)
    lock = tomllib.loads(Path("uv.lock").read_text())
    for package in lock["package"]:
        if package["name"] not in PACKAGES:
            continue
        candidates = [
            wheel
            for wheel in package["wheels"]
            if "manylinux" in wheel["url"]
            and "x86_64" in wheel["url"]
            and ("cp312-cp312" in wheel["url"] or "cp37-abi3" in wheel["url"])
        ]
        if len(candidates) != 1:
            raise RuntimeError("No unique locked CPU OCR wheel")
        download(candidates[0], directory)


if __name__ == "__main__":
    main()
