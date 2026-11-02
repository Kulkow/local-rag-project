"""Generate image-only PDFs from synthetic text PDFs, without Pillow or fixture files."""

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
import subprocess

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject


@pytest.fixture
def rasterize_pdf(tmp_path: Path) -> Callable[[bytes], bytes]:
    def rasterize(content: bytes) -> bytes:
        source = tmp_path / "text.pdf"
        source.write_bytes(content)
        writer = PdfWriter()
        for number, original in enumerate(PdfReader(BytesIO(content)).pages, 1):
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(number),
                    "-l",
                    str(number),
                    "-singlefile",
                    "-scale-to",
                    "1800",
                    str(source),
                    str(tmp_path / "scan"),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            with (tmp_path / "scan.ppm").open("rb") as stream:
                assert stream.readline() == b"P6\n"
                width, height = map(int, stream.readline().split())
                assert stream.readline() == b"255\n"
                pixels = stream.read()
            image = DecodedStreamObject()
            image.set_data(pixels)
            image.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(width),
                    NameObject("/Height"): NumberObject(height),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            w, h = float(original.mediabox.width), float(original.mediabox.height)
            page = writer.add_blank_page(width=w, height=h)
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/XObject"): DictionaryObject(
                        {
                            NameObject("/Scan"): writer._add_object(image.flate_encode()),
                        }
                    ),
                }
            )
            drawing = DecodedStreamObject()
            drawing.set_data(f"q {w} 0 0 {h} 0 0 cm /Scan Do Q".encode())
            page[NameObject("/Contents")] = writer._add_object(drawing)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    return rasterize
