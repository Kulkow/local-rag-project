from uuid import uuid4

import pytest

from app.modules.documents.domain.chunking import ChunkingConfig, chunk_pages
from app.modules.documents.domain.extraction import PageText


def test_chunking_is_deterministic_overlapping_and_page_scoped() -> None:
    document_id = uuid4()
    pages = (PageText(1, "abcdefghij"), PageText(2, ""), PageText(3, "klmnop"))
    config = ChunkingConfig(size=6, overlap=2)
    chunks = chunk_pages(document_id, "checksum", pages, config)
    assert [(c.page_number, c.start_offset, c.end_offset, c.text) for c in chunks] == [
        (1, 0, 6, "abcdef"),
        (1, 4, 10, "efghij"),
        (3, 0, 6, "klmnop"),
    ]
    assert chunk_pages(document_id, "checksum", pages, config) == chunks
    assert len({c.id for c in chunks}) == 3
    assert chunks[0].id != chunk_pages(uuid4(), "checksum", pages, config)[0].id


@pytest.mark.parametrize("size,overlap", [(0, 0), (6, -1), (6, 6), (6, 7)])
def test_bad_chunk_settings_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(size=size, overlap=overlap)


def test_unicode_offsets_are_character_offsets_and_blank_chunks_are_skipped() -> None:
    pages = (PageText(1, "Привет мир 🌍"),)
    chunks = chunk_pages(uuid4(), "checksum", pages, ChunkingConfig(size=6, overlap=1))
    for chunk in chunks:
        assert chunk.text == pages[0].text[chunk.start_offset : chunk.end_offset]
        assert len(chunk.text) <= 6
    assert chunks[-1].end_offset == len(pages[0].text)
