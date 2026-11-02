"""Real PDF parser, synthetic fixtures only; no LLM needed."""

from io import BytesIO
from collections.abc import Callable
import asyncio
from pathlib import Path
import sys

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.modules.documents.infrastructure.pdf_extractor import PdfExtractor
from app.modules.documents.domain.extraction import ExtractionFailure, PageText


def synthetic_pdf(*, text: bool = True, encrypted: bool = False, pages: int = 2) -> bytes:
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if text and index == 0:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 72 720 Td (Synthetic evidence) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def test_real_pdf_preserves_page_numbers_and_blank_pages() -> None:
    result = await PdfExtractor().extract(synthetic_pdf())
    assert result.pages == (PageText(1, "Synthetic evidence"), PageText(2, ""))


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (synthetic_pdf(text=False), "no_text"),
        (synthetic_pdf(encrypted=True), "pdf_encrypted"),
        (b"%PDF-1.4\n%%EOF", "pdf_invalid"),
        (synthetic_pdf(pages=201), "pdf_page_limit"),
    ],
)
async def test_pdf_rejections(content: bytes, code: str) -> None:
    with pytest.raises(ExtractionFailure) as error:
        await PdfExtractor().extract(content)
    assert error.value.code == code


async def test_parser_timeout_reaps_process() -> None:
    with pytest.raises(ExtractionFailure) as error:
        await PdfExtractor(timeout_seconds=0.000001).extract(synthetic_pdf())
    assert error.value.code == "pdf_timeout"


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_stop_descendants_and_clean_directory(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    launch = asyncio.create_subprocess_exec
    started = asyncio.Event()
    processes = []
    directories = []

    async def slow_parser(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        directory = Path(args[-1])
        directories.append(directory)
        # A descendant inherits stdout: communicate cannot finish until it too is killed.
        process = await launch(
            sys.executable,
            "-c",
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "time.sleep(60)",
            **kwargs,
        )
        processes.append(process)
        (directory / "private-page.ppm").write_bytes(b"private pixels")
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_parser)
    task = asyncio.create_task(PdfExtractor(timeout_seconds=0.5).extract(synthetic_pdf()))
    await started.wait()
    if cancel:
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    else:
        with pytest.raises(ExtractionFailure, match="pdf_timeout"):
            await asyncio.wait_for(task, 3)
    assert processes[0].returncode is not None
    assert not directories[0].exists()


def test_text_normalization_removes_controls() -> None:
    assert PageText(1, "  e\u0301\x00 \r\nline  ").text == "é\nline"


@pytest.fixture
def scanned_pdf(rasterize_pdf: Callable[[bytes], bytes]) -> bytes:
    return rasterize_pdf(synthetic_pdf(pages=1))


async def test_scan_recognized_without_text_layer(scanned_pdf: bytes) -> None:
    assert PdfReader(BytesIO(scanned_pdf)).pages[0].extract_text() == ""
    result = await PdfExtractor().extract(scanned_pdf)
    assert "Synthetic evidence" in result.pages[0].text
    assert result.pages[0].page_number == 1


async def test_mixed_pdf_preserves_pages_and_reads_images_next_to_text(scanned_pdf: bytes) -> None:
    writer = PdfWriter()
    native = PdfReader(BytesIO(synthetic_pdf()))
    writer.add_page(native.pages[0])
    scan = writer.add_page(PdfReader(BytesIO(scanned_pdf)).pages[0])
    # Place a native footer on the same page as the scanned text.
    footer = PdfReader(BytesIO(synthetic_pdf(pages=1))).pages[0]
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 72 Td (Native footer) Tj ET")
    footer[NameObject("/Contents")] = stream
    scan.merge_page(footer)
    writer.add_page(native.pages[1])
    output = BytesIO()
    writer.write(output)
    result = await PdfExtractor().extract(output.getvalue())
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert result.pages[0].text == "Synthetic evidence"
    assert "Synthetic evidence" in result.pages[1].text
    assert "Native footer" in result.pages[1].text
    assert result.pages[1].text.count("Synthetic evidence") == 1
    assert result.pages[2].text == ""
