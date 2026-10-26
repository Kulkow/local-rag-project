"""Versioned character-window baseline, independent of providers and tokenizers."""

from dataclasses import dataclass
from uuid import UUID, NAMESPACE_URL, uuid5

from app.modules.documents.domain.extraction import PageText

CHUNKER_VERSION = "page-characters-v1"


@dataclass(frozen=True)
class ChunkingConfig:
    size: int = 1000
    overlap: int = 150

    def __post_init__(self) -> None:
        if self.size <= 0 or not 0 <= self.overlap < self.size:
            raise ValueError("Require size > 0 and 0 <= overlap < size")


@dataclass(frozen=True)
class DocumentChunk:
    id: UUID
    document_id: UUID
    ordinal: int
    page_number: int
    start_offset: int
    end_offset: int
    text: str


def chunk_pages(
    document_id: UUID, checksum: str, pages: tuple[PageText, ...], config: ChunkingConfig
) -> tuple[DocumentChunk, ...]:
    chunks: list[DocumentChunk] = []
    for page in pages:
        for start in range(0, len(page.text), config.size - config.overlap):
            end = min(start + config.size, len(page.text))
            text = page.text[start:end]
            if text.strip():
                key = f"{CHUNKER_VERSION}:{document_id}:{checksum}:{config.size}:{config.overlap}:{page.page_number}:{start}:{end}"
                chunks.append(
                    DocumentChunk(
                        uuid5(NAMESPACE_URL, key),
                        document_id,
                        len(chunks),
                        page.page_number,
                        start,
                        end,
                        text,
                    )
                )
            if end == len(page.text):
                break
    return tuple(chunks)
