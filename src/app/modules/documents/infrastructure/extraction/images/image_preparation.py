"""Prepare camera images only inside the resource-limited OCR child."""

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
import cv2
import numpy as np
from cv2.typing import MatLike

from app.modules.documents.domain.extraction import ExtractionFailure

MAX_PIXELS = 20_000_000
MAX_SIDE = 3200


def prepare_image(source: Path, directory: Path) -> Path:
    """Apply phone orientation, flatten transparency and enhance bounded grayscale pixels."""
    target = directory / "prepared.png"
    try:
        cv2.setNumThreads(1)
        cv2.ocl.setUseOpenCL(False)
        with Image.open(source) as original:
            width, height = original.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise ExtractionFailure("image_invalid")
            # EXIF orientation describes how the stored camera pixels must be displayed.
            ImageOps.exif_transpose(original, in_place=True)
            original.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            if original.mode in ("RGBA", "LA") or "transparency" in original.info:
                rgba = original.convert("RGBA")
                white = Image.new("RGBA", rgba.size, "white")
                white.alpha_composite(rgba)
                grayscale = white.convert("L")
            else:
                grayscale = original.convert("L")
        # Small text benefits from larger character pixels, without unbounded upsampling.
        scale = min(2.0, MAX_SIDE / max(grayscale.size))
        if scale > 1:
            grayscale = grayscale.resize(
                (round(grayscale.width * scale), round(grayscale.height * scale)),
                Image.Resampling.LANCZOS,
            )
        pixels: MatLike = np.asarray(grayscale)
        if np.count_nonzero(pixels < 127) > pixels.size / 2:
            pixels = cv2.bitwise_not(pixels)
        pixels = (
            cv2.normalize(pixels, np.empty_like(pixels), 0, 255, cv2.NORM_MINMAX)
            if pixels.ptp()
            else pixels
        )
        pixels = cv2.bilateralFilter(pixels, 5, 25, 25)
        pixels = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(pixels)
        pixels = deskew(pixels)
        pixels = cv2.copyMakeBorder(pixels, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255,))
        if not cv2.imwrite(str(target), pixels):
            raise OSError("Cannot save prepared image")
        return target
    except (OSError, ValueError, UnidentifiedImageError, cv2.error):
        target.unlink(missing_ok=True)
        raise ExtractionFailure("ocr_failed") from None


def deskew(pixels: MatLike) -> MatLike:
    """Correct small line skew only when several near-horizontal edges agree."""
    edges = cv2.Canny(pixels, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 1800,
        threshold=80,
        minLineLength=max(60, pixels.shape[1] // 8),
        maxLineGap=20,
    )
    if lines is None:
        return pixels
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = float(np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1))))
        if abs(angle) <= 7:
            angles.append(angle)
    if len(angles) < 5:
        return pixels
    angle = float(np.median(angles))
    if abs(angle) < 0.3 or float(np.std(angles)) > 2:
        return pixels
    height, width = pixels.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        pixels,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255,),
    )
