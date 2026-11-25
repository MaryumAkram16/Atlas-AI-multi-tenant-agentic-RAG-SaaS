"""Ingestion worker process.

python -m app.workers.main          # poll forever (docker compose, a VM)
python -m app.workers.main --drain  # process due jobs until the queue is empty,
                                    # then exit (Cloud Run Job on a schedule)
"""

import argparse
import logging
import os
import signal
import socket
import threading
import time

from app.config import get_settings
from app.observability.logging import configure_logging
from app.workers.ingestion import IngestionWorker

logger = logging.getLogger("app.worker")


def _worker(worker: IngestionWorker | None) -> IngestionWorker:
    if worker is not None:
        return worker
    return IngestionWorker.from_settings(
        get_settings(), worker_id=f"{socket.gethostname()}:{os.getpid()}"
    )


def run(stop: threading.Event, worker: IngestionWorker | None = None) -> None:
    settings = get_settings()
    worker = _worker(worker)
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


def drain(
    stop: threading.Event, worker: IngestionWorker | None = None, *, max_seconds: float = 840
) -> int:
    """Process jobs until none is due (or time runs out); return how many ran."""
    worker = _worker(worker)
    deadline = time.monotonic() + max_seconds
    processed = 0
    try:
        worker.index.ensure_collection()
        while not stop.is_set() and time.monotonic() < deadline:
            if not worker.run_once():
                break
            processed += 1
    finally:
        worker.close()
    logger.info("worker drained jobs=%s", processed)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.workers.main")
    parser.add_argument("--drain", action="store_true", help="exit when the queue is empty")
    parser.add_argument("--max-seconds", type=float, default=840, help="drain time budget")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_format == "json")
    from app.observability.tracing import setup_tracing

    setup_tracing("atlas-worker", settings.otel_exporter_otlp_endpoint)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    if args.drain:
        drain(stop, max_seconds=args.max_seconds)
    else:
        run(stop)


if __name__ == "__main__":
    main()
