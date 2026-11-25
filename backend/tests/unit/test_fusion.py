import pytest

from app.retrieval.fusion import rrf_fuse


def test_rrf_rewards_agreement():
    dense = ["a", "b", "c"]
    sparse = ["c", "a", "d"]
    fused = rrf_fuse([dense, sparse], k=60, limit=10)
    ids = [i for i, _ in fused]
    assert ids[:2] == ["a", "c"]  # both lists contain them near the top
    assert set(ids) == {"a", "b", "c", "d"}
    score = dict(fused)
    assert score["a"] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_limit_and_single_list():
    assert [i for i, _ in rrf_fuse([["x", "y", "z"]], k=60, limit=2)] == ["x", "y"]
    assert rrf_fuse([[], []], k=60, limit=5) == []


def test_rrf_ties_are_stable():
    fused = rrf_fuse([["a", "b"], ["b", "a"]], k=60, limit=2)
    assert [i for i, _ in fused] == ["a", "b"]  # equal scores keep first-seen order
