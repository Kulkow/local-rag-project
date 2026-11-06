"""Bounded header checks; actual image decoding runs in an isolated OCR process."""

MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 12_000
IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg"})


def valid_image(content: bytes, content_type: str) -> bool:
    dimensions = _dimensions(content, content_type)
    if dimensions is None:
        return False
    width, height = dimensions
    return (
        0 < width <= MAX_IMAGE_SIDE
        and 0 < height <= MAX_IMAGE_SIDE
        and width * height <= MAX_IMAGE_PIXELS
    )


def _dimensions(content: bytes, content_type: str) -> tuple[int, int] | None:
    if content_type == "image/png":
        if (
            len(content) < 45
            or not content.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
            or not content.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
        ):
            return None
        return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
    if content_type != "image/jpeg" or not content.startswith(b"\xff\xd8\xff"):
        return None
    if not content.endswith(b"\xff\xd9"):
        return None
    offset = 2
    # JPEG segment lengths bound this walk by the already bounded upload size.
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            return None
        offset += 1
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            return None
        marker = content[offset]
        offset += 1
        if marker in (0x00, 0xD8, 0xD9, 0xDA) or offset + 2 > len(content):
            return None
        length = int.from_bytes(content[offset : offset + 2], "big")
        if length < 2 or offset + length > len(content):
            return None
        if marker in (0xC0, 0xC1, 0xC2):
            if length < 8:
                return None
            return (
                int.from_bytes(content[offset + 5 : offset + 7], "big"),
                int.from_bytes(content[offset + 3 : offset + 5], "big"),
            )
        offset += length
    return None
