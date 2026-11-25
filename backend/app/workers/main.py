"""Ingestion worker process: `python -m app.workers.main`."""

import logging
import os
import signal
import socket
import threading

from app.config import get_settings
from app.observability.logging import configure_logging
from app.workers.ingestion import IngestionWorker

logger = logging.getLogger("app.worker")


def run(stop: threading.Event, worker: IngestionWorker | None = None) -> None:
    settings = get_settings()
    if worker is None:
        worker = IngestionWorker.from_settings(
            settings, worker_id=f"{socket.gethostname()}:{os.getpid()}"
        )
    try:
        worker.index.ensure_collection()
        logger.info("worker started")
        while not stop.is_set():
            try:
                busy = worker.run_once()
            except Exception:
                logger.exception("worker loop error")
                busy = False
            if not busy:
                stop.wait(settings.worker_poll_interval_seconds)
    finally:
        worker.close()
        logger.info("worker stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_format == "json")
    from app.observability.tracing import setup_tracing

    setup_tracing("atlas-worker", settings.otel_exporter_otlp_endpoint)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(stop)


if __name__ == "__main__":
    main()
