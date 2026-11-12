from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
import pytest

from app.modules.documents.domain.extraction import ExtractionFailure
from app.modules.documents.infrastructure.extraction.images.image_extractor import ImageExtractor
from app.modules.documents.infrastructure.extraction.images.image_preparation import prepare_image


@pytest.mark.parametrize("variant", ["png", "jpeg", "low_contrast", "inverted", "exif"])
async def test_real_russian_ocr(
    russian_image: Image.Image, variant: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OCR_MODELS_DIR", str(tmp_path / "missing-models"))
    image = russian_image
    ImageDraw.Draw(image).text(
        (650, 315),
        "Invoice ABC-123",
        fill="black",
        font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40),
    )
    if variant == "low_contrast":
        image = image.convert("L").point(lambda value: 140 + value * 60 // 255)
    if variant == "inverted":
        image = ImageOps.invert(image)
    exif = Image.Exif()
    if variant == "exif":
        image = image.transpose(Image.Transpose.ROTATE_90)
        exif[274] = 6  # Pixels stored sideways; phone display rotates clockwise.
    output = BytesIO()
    jpeg = variant in ("jpeg", "exif")
    image.save(output, format="JPEG" if jpeg else "PNG", exif=exif, quality=92)
    result = await ImageExtractor("image/jpeg" if jpeg else "image/png").extract(output.getvalue())
    assert result.ocr_engine == "tesseract"
    assert result.ocr_fallback_reason == "paddle_models_missing"
    text = result.pages[0].text.lower()
    for expected in (
        "заявление",
        "справки",
        "договор",
        "квартиры",
        "оплата",
        "ноябрь",
        "12345",
        "invoice",
    ):
        assert expected in text, (variant, text)


def test_preparation_flattens_transparency_and_bounds_scaling(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (100, 200), (0, 0, 0, 0)).save(source)
    prepared = prepare_image(source, tmp_path)
    with Image.open(prepared) as image:
        assert image.mode == "L"
        assert image.size == (240, 440)
        assert image.getextrema() == (255, 255)


def test_preparation_rejects_corrupt_image_without_exposing_paths(tmp_path: Path) -> None:
    source = tmp_path / "private.png"
    source.write_bytes(b"corrupt pixels")
    with pytest.raises(ExtractionFailure, match="^ocr_failed$"):
        prepare_image(source, tmp_path)
    assert not (tmp_path / "prepared.png").exists()
