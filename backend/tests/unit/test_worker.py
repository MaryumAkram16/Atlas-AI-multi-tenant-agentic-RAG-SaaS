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


class QueueWorker(FakeWorker):
    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    def run_once(self):
        if self.jobs:
            self.jobs -= 1
            return True
        return False


def test_drain_processes_until_empty_then_exits():
    from app.workers.main import drain

    worker = QueueWorker(jobs=3)
    assert drain(threading.Event(), worker, max_seconds=5) == 3
    assert worker.closed


def test_drain_respects_its_time_budget():
    from app.workers.main import drain

    class Endless(FakeWorker):
        def run_once(self):
            return True

    assert drain(threading.Event(), Endless(), max_seconds=0) == 0
