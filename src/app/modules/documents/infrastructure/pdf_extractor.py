from app.modules.documents.infrastructure.isolated_extractor import IsolatedExtractor


class PdfExtractor(IsolatedExtractor):
    content_type = "application/pdf"
    name = "pypdf-6.21.2/tesseract-rus+eng/pages-v2"
    process_module = "app.modules.documents.infrastructure.pdf_process"
    error_prefix = "pdf"
