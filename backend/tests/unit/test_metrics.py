import math

from app.evaluation.metrics import mrr, ndcg_at_k, percentile, recall_at_k


def test_recall_at_k():
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, k=2) == 0.5
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, k=3) == 1.0


def test_mrr():
    assert mrr(["x", "y", "a"], {"a"}) == 1 / 3
    assert mrr(["x"], {"a"}) == 0.0


def test_ndcg_binary():
    assert ndcg_at_k(["a", "b"], {"a", "b"}, k=10) == 1.0
    expected = (1 / math.log2(3)) / 1.0
    assert math.isclose(ndcg_at_k(["x", "a"], {"a"}, k=10), expected)
    assert ndcg_at_k(["x"], {"a"}, k=10) == 0.0


def test_percentile():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 95) == 10
