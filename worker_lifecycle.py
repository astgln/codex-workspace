"""Cooperative service shutdown; signals never cancel an accepted CLI turn."""
from contextlib import contextmanager
import signal
import threading


@contextmanager
def shutdown_event():
    stop = threading.Event()
    previous = {}
    def request_stop(signum, frame):
        stop.set()
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, request_stop)
        yield stop
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
