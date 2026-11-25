import threading

from app.workers.main import run


def test_worker_exits_when_stop_is_set():
    stop = threading.Event()
    stop.set()
    t = threading.Thread(target=run, args=(stop,))
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()
