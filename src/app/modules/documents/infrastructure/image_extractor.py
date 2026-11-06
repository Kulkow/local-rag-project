from app.modules.documents.domain.images import IMAGE_MEDIA_TYPES
from app.modules.documents.infrastructure.isolated_extractor import IsolatedExtractor


class ImageExtractor(IsolatedExtractor):
    name = "tesseract-rus+eng/image-v1"
    process_module = "app.modules.documents.infrastructure.image_process"
    error_prefix = "image"

    def __init__(self, content_type: str, timeout_seconds: float = 30) -> None:
        if content_type not in IMAGE_MEDIA_TYPES:
            raise ValueError("Unsupported OCR image type")
        super().__init__(timeout_seconds)
        self.content_type = content_type
