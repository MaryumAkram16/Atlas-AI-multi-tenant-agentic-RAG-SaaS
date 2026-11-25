"""Ingestion worker placeholder.

The Postgres-backed job queue arrives in Week 2 (see docs/decisions/0002).
For now the worker idles and shuts down cleanly on SIGTERM/SIGINT.
"""

import logging
import signal
import threading

from app.config import get_settings
from app.observability.logging import configure_logging

logger = logging.getLogger("app.worker")


def run(stop: threading.Event) -> None:
    settings = get_settings()
    logger.info("worker started; no job queue yet")
    while not stop.wait(settings.worker_poll_interval_seconds):
        logger.debug("worker idle")
    logger.info("worker stopped")


def main() -> None:
    configure_logging(get_settings().log_level)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(stop)


if __name__ == "__main__":
    main()
