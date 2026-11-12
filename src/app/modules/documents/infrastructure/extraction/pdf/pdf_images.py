"""Detect drawn PDF images without decoding their pixel data in Python."""

from typing import cast

from pypdf import PageObject, PdfReader
from pypdf.generic import ContentStream, DictionaryObject

from app.modules.documents.domain.extraction import ExtractionFailure


def page_has_images(page: PageObject, reader: PdfReader) -> bool:
    resources = cast(DictionaryObject, page.get("/Resources", DictionaryObject()))
    pending = [(page.get_contents(), resources)]
    visited: set[int] = set()
    while pending:
        content, resources = pending.pop()
        if content is None:
            continue
        if len(content.get_data()) > 16 * 1024 * 1024:
            raise ExtractionFailure("pdf_resource_limit")
        objects = cast(DictionaryObject, resources.get("/XObject", DictionaryObject()))
        for operands, operator in content.operations:
            if operator == b"INLINE IMAGE":
                return True
            if operator != b"Do" or not operands:
                continue
            obj = objects[operands[0]].get_object()
            if not isinstance(obj, DictionaryObject):
                continue
            if obj.get("/Subtype") == "/Image":
                return True
            if obj.get("/Subtype") == "/Form" and id(obj) not in visited:
                visited.add(id(obj))
                pending.append(
                    (
                        ContentStream(obj, reader),
                        cast(DictionaryObject, obj.get("/Resources", resources)),
                    )
                )
    return False
