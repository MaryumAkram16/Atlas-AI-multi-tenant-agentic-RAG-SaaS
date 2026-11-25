import threading

from app.workers.main import run


class FakeIndex:
    def ensure_collection(self):
        pass


class FakeWorker:
    def __init__(self):
        self.index = FakeIndex()
        self.closed = False

    def run_once(self):
        return False

    def close(self):
        self.closed = True


def test_worker_exits_when_stop_is_set():
    stop = threading.Event()
    stop.set()
    worker = FakeWorker()
    t = threading.Thread(target=run, args=(stop, worker))
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()
    assert worker.closed
