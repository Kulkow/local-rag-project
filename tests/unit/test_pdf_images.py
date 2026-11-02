from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.modules.documents.infrastructure.pdf_images import page_has_images


@pytest.mark.parametrize("nested", [False, True])
def test_inline_images_detected_without_pillow(nested: bool) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    drawing = DecodedStreamObject()
    drawing.set_data(b"q 10 0 0 10 0 0 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\xff\xff EI Q")
    if nested:
        drawing.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/XObject"): DictionaryObject(
                    {
                        NameObject("/Form"): writer._add_object(drawing),
                    }
                ),
            }
        )
        drawing = DecodedStreamObject()
        drawing.set_data(b"/Form Do")
    page[NameObject("/Contents")] = writer._add_object(drawing)
    output = BytesIO()
    writer.write(output)
    reader = PdfReader(BytesIO(output.getvalue()))
    assert page_has_images(reader.pages[0], reader)
