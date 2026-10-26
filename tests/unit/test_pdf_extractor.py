"""Real PDF parser, synthetic fixtures only; no LLM needed."""

from io import BytesIO

import pytest
from pypdf import PdfWriter
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
        (synthetic_pdf(text=False), "pdf_needs_ocr"),
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


def test_text_normalization_removes_controls() -> None:
    assert PageText(1, "  e\u0301\x00 \r\nline  ").text == "é\nline"
