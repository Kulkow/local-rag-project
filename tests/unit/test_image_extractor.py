from collections.abc import Callable

import pytest

from app.modules.documents.domain.entities import validate_file
from app.modules.documents.domain.extraction import ExtractionFailure
from app.modules.documents.infrastructure.extractors import default_extractors
from app.modules.documents.infrastructure.image_extractor import ImageExtractor
from app.modules.shared.domain.errors import ApplicationError
from test_pdf_extractor import synthetic_pdf


@pytest.mark.parametrize("extension", ["png", "jpg", "jpeg"])
async def test_image_upload_validation_and_real_tesseract(
    image_from_pdf: Callable[[bytes, str], bytes], extension: str
) -> None:
    content = image_from_pdf(synthetic_pdf(pages=1), extension)
    mime = "image/png" if extension == "png" else "image/jpeg"
    assert validate_file(f"scan.{extension}", mime, content)[0] == mime
    assert (
        validate_file(f"SCAN.{extension.upper()}", "application/octet-stream", content)[0] == mime
    )
    result = await default_extractors().for_mime(mime).extract(content)
    assert len(result.pages) == 1 and result.pages[0].page_number == 1
    assert "Synthetic evidence" in result.pages[0].text


@pytest.mark.parametrize("extension,mime", [("png", "image/png"), ("jpg", "image/jpeg")])
def test_image_rejects_disguised_truncated_and_oversized_pixels(
    image_from_pdf: Callable[[bytes, str], bytes], extension: str, mime: str
) -> None:
    content = image_from_pdf(synthetic_pdf(pages=1), extension)
    invalid = [b"not an image", content[:20], content[:-2]]
    if extension == "png":
        invalid.append(content[:16] + (20_000).to_bytes(4, "big") + content[20:])
        invalid.append(content[:16] + (5000).to_bytes(4, "big") * 2 + content[24:])
        invalid.append(content[:16] + b"\0" * 4 + content[20:])
    else:
        # JPEG SOF0 height/width follow length and precision.
        offset = content.index(b"\xff\xc0") + 5
        invalid.append(content[:offset] + (20_000).to_bytes(2, "big") + content[offset + 2 :])
    for data in invalid:
        with pytest.raises(ApplicationError) as error:
            validate_file(f"scan.{extension}", mime, data)
        assert error.value.code == "unsupported_media"
    with pytest.raises(ApplicationError):
        validate_file(f"scan.{extension}", "text/html", content)
    with pytest.raises(ApplicationError):
        validate_file("disguised.pdf", "application/pdf", content)


async def test_image_decoder_failure_is_safe() -> None:
    with pytest.raises(ExtractionFailure, match="image_invalid"):
        await ImageExtractor("image/png").extract(b"bad image")


async def test_valid_header_without_pixel_data_fails_in_isolated_decoder(
    image_from_pdf: Callable[[bytes, str], bytes],
) -> None:
    content = image_from_pdf(synthetic_pdf(pages=1), "png")
    # A complete IHDR and IEND pass bounded upload checks, but have no image data.
    damaged = content[:33] + content[-12:]
    assert validate_file("damaged.png", "image/png", damaged)[0] == "image/png"
    with pytest.raises(ExtractionFailure, match="ocr_failed"):
        await ImageExtractor("image/png").extract(damaged)


async def test_blank_image_returns_no_text(image_from_pdf: Callable[[bytes, str], bytes]) -> None:
    with pytest.raises(ExtractionFailure, match="no_text"):
        await ImageExtractor("image/png").extract(image_from_pdf(synthetic_pdf(text=False), "png"))


async def test_image_timeout(image_from_pdf: Callable[[bytes, str], bytes]) -> None:
    with pytest.raises(ExtractionFailure, match="image_timeout"):
        await ImageExtractor("image/png", timeout_seconds=0.000001).extract(
            image_from_pdf(synthetic_pdf(pages=1), "png")
        )


def test_image_extractor_rejects_unsupported_formats() -> None:
    with pytest.raises(ValueError, match="Unsupported OCR image type"):
        ImageExtractor("image/svg+xml")


def test_jpeg_headers_reject_invalid_lengths_and_accept_progressive_frames(
    image_from_pdf: Callable[[bytes, str], bytes],
) -> None:
    from app.modules.documents.domain.images import valid_image

    content = image_from_pdf(synthetic_pdf(pages=1), "jpg")
    offset = content.index(b"\xff\xc0")
    # SOF2 has the same dimension fields as SOF0; decoding remains the child's job.
    assert valid_image(content[:offset] + b"\xff\xc2" + content[offset + 2 :], "image/jpeg")
    for length in (0, 1, 7, 65535):
        invalid = content[: offset + 2] + length.to_bytes(2, "big") + content[offset + 4 :]
        assert not valid_image(invalid, "image/jpeg")
    assert not valid_image(b"\xff\xd8\xff\xff\xff\xd9", "image/jpeg")
