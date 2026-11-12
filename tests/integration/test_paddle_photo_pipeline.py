"""Explicit neural OCR smoke; ordinary unit tests never need downloaded models."""

from io import BytesIO
import os

from PIL import Image, ImageDraw, ImageFont
import pytest

from app.modules.documents.infrastructure.extraction.images.image_extractor import ImageExtractor


@pytest.mark.skipif(
    os.getenv("TEST_PADDLE_OCR") != "1",
    reason="Set TEST_PADDLE_OCR=1 after initializing OCR models",
)
@pytest.mark.parametrize("variant", ["normal", "skew", "exif"])
async def test_real_paddle_russian_primary(russian_image: Image.Image, variant: str) -> None:
    image = russian_image
    exif = Image.Exif()
    if variant == "exif":
        image = image.transpose(Image.Transpose.ROTATE_90)
        exif[274] = 6
    if variant == "skew":
        image = image.rotate(3, resample=Image.Resampling.BICUBIC, fillcolor="white")
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif, quality=92)
    result = await ImageExtractor("image/jpeg").extract(output.getvalue())
    assert result.ocr_engine == "paddleocr", result.ocr_fallback_reason
    assert result.ocr_fallback_reason is None
    text = result.pages[0].text.lower()
    for expected in ("заявление", "договор", "квартиры", "оплата", "12345"):
        assert expected in text, (variant, text)


@pytest.mark.skipif(
    os.getenv("TEST_PADDLE_OCR") != "1",
    reason="Set TEST_PADDLE_OCR=1 after initializing OCR models",
)
async def test_real_mixed_language_preserves_latin_words(russian_image: Image.Image) -> None:
    draw = ImageDraw.Draw(russian_image)
    draw.rectangle((0, 300, 1400, 400), fill="white")
    draw.text(
        (45, 315),
        "Номер документа: 12345. Invoice ABC-123",
        fill="black",
        font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40),
    )
    output = BytesIO()
    russian_image.save(output, format="JPEG", quality=92)
    result = await ImageExtractor("image/jpeg").extract(output.getvalue())
    assert result.ocr_engine in {"paddleocr", "tesseract"}
    if result.ocr_engine == "tesseract":
        assert result.ocr_fallback_reason == "paddle_mixed_script"
    else:
        assert result.ocr_fallback_reason is None
    text = result.pages[0].text.lower()
    assert "invoice" in text and "договор" in text and "12345" in text
