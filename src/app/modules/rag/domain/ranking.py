"""Rank fusion independent of incomparable keyword and cosine score scales."""

from collections.abc import Sequence
from uuid import UUID


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[UUID]], k: int = 60
) -> list[tuple[UUID, float]]:
    if k < 1:
        raise ValueError("RRF k must be positive")
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        seen: set[UUID] = set()
        for item in ranking:
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + len(seen))
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
