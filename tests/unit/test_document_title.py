import pytest

from app.modules.documents.domain.extraction import ExtractedContent, PageText


@pytest.mark.parametrize(
    "pages,expected",
    [
        (("\n  Отчёт   за 2026 год\nДальнейший текст",), "Отчёт за 2026 год"),
        (("1\n2026", "Project manual\nDetails"), "Project manual"),
        (("123\n---",), None),
        (("A" * 400,), "A" * 255),
        (("<script>alert(1)</script>\nText",), "<script>alert(1)</script>"),
    ],
)
def test_title_comes_from_first_meaningful_transcript_line(
    pages: tuple[str, ...], expected: str | None
) -> None:
    content = ExtractedContent(
        tuple(PageText(number, text) for number, text in enumerate(pages, 1))
    )
    assert content.title == expected
