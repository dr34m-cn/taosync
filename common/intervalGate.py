import threading
import time


class IntervalGate:
    """Reserve evenly spaced request slots per key, shared by all threads."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self._lock = threading.Lock()
        self._nextSlot = {}
        self._clock = clock
        self._sleep = sleep

    def wait(self, key, interval):
        try:
            interval = float(interval or 0)
        except (TypeError, ValueError):
            interval = 0.0
        if interval <= 0:
            return 0.0
        with self._lock:
            now = self._clock()
            slot = max(now, self._nextSlot.get(key, now))
            self._nextSlot[key] = slot + interval
        delay = slot - now
        if delay > 0:
            self._sleep(delay)
        return max(delay, 0.0)
