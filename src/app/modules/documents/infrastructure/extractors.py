from app.modules.documents.application.extraction import ExtractorRegistry
from app.modules.documents.infrastructure.image_extractor import ImageExtractor
from app.modules.documents.infrastructure.pdf_extractor import PdfExtractor


def default_extractors() -> ExtractorRegistry:
    return ExtractorRegistry(
        [PdfExtractor(), ImageExtractor("image/png"), ImageExtractor("image/jpeg")]
    )
