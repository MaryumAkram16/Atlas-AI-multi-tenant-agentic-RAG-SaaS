"""Reciprocal Rank Fusion."""

from collections.abc import Hashable, Sequence


def rrf_fuse[T: Hashable](
    rankings: Sequence[Sequence[T]], *, k: int = 60, limit: int = 20
) -> list[tuple[T, float]]:
    """score(d) = sum over rankings of 1 / (k + rank), rank starting at 1.
    Ties keep first-seen order, so results are deterministic."""
    scores: dict[T, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    order = {item: i for i, item in enumerate(scores)}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))
    return ranked[:limit]
