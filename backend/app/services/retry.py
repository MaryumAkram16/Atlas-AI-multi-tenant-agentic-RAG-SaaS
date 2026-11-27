"""Retry policy for model/embedding providers: busy or rate-limited responses
(429, 5xx) are retried a few times with exponential backoff, honouring a short
Retry-After. Other errors fail at once."""

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 10.0


def backoff(attempt: int, base: float, retry_after: str | None = None) -> float:
    """Seconds to wait before retry number `attempt` (1-based)."""
    if retry_after:
        try:
            return min(float(retry_after), MAX_RETRY_AFTER)
        except ValueError:
            pass
    return base * (2 ** (attempt - 1))


class ProviderError(RuntimeError):
    """A model or embedding provider returned an HTTP error. Carries only the
    status code (response bodies can echo prompt or document text)."""

    def __init__(self, what: str, status: int) -> None:
        super().__init__(f"{what} failed with status {status}")
        self.status = status
