from uuid import UUID

import pytest

from app.modules.rag.domain.ranking import reciprocal_rank_fusion
from app.modules.rag.application.reranking import valid_order


def test_rrf_fuses_ranks_and_deduplicates_per_list() -> None:
    a, b, c = [UUID(int=i) for i in (1, 2, 3)]
    result = reciprocal_rank_fusion([[a, b, a], [b, c]])
    assert [id for id, _ in result] == [b, a, c]
    assert result[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert reciprocal_rank_fusion([[a, b], []]) == [(a, 1 / 61), (b, 1 / 62)]
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[b], [a]])[0][0] == a
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[a]], 0)


@pytest.mark.parametrize("order", [None, [0], [0, 0], [0, 2], [True, 0], ["0", 1]])
def test_reranker_cannot_add_omit_or_duplicate_evidence(order: object) -> None:
    assert not valid_order(order, 2)
    assert valid_order([1, 0], 2)
