"""Optional, bounded query transformation; rewritten text is never answer evidence."""

from typing import Protocol


class QueryRewriter(Protocol):
    async def rewrite(self, question: str) -> str | None: ...


def validated_rewrite(question: str, rewritten: object) -> str | None:
    if not isinstance(rewritten, str):
        return None
    normalized = " ".join(rewritten.split())
    if not normalized or len(normalized) > 200 or any(ord(char) < 32 for char in rewritten):
        return None
    if normalized.casefold() == " ".join(question.split()).casefold():
        return None
    return normalized
