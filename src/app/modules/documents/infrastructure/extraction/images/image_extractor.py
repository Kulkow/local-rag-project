from app.modules.documents.domain.images import IMAGE_MEDIA_TYPES
from app.modules.documents.infrastructure.extraction.isolated_extractor import IsolatedExtractor


class ImageExtractor(IsolatedExtractor):
    name = "opencv/paddleocr-eslav-v5/tesseract-rus+eng/image-v3"
    process_module = "app.modules.documents.infrastructure.extraction.images.image_process"
    error_prefix = "image"

    def __init__(self, content_type: str, timeout_seconds: float = 100) -> None:
        if content_type not in IMAGE_MEDIA_TYPES:
            raise ValueError("Unsupported OCR image type")
        super().__init__(timeout_seconds)
        self.content_type = content_type
