import pytest

from app.workers.queue import backoff_seconds


@pytest.mark.parametrize("attempt", range(1, 12))
def test_backoff_is_bounded_and_grows(attempt):
    base, cap = 5.0, 300.0
    ceiling = min(cap, base * 2 ** (attempt - 1))
    for _ in range(50):
        delay = backoff_seconds(attempt, base=base, cap=cap)
        assert ceiling / 2 <= delay <= ceiling


def test_zero_base_means_immediate_retry():
    assert backoff_seconds(3, base=0, cap=300) == 0
