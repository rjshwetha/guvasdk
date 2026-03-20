import time
import collections

class EventCounter:
    def __init__(self, window_seconds: float):
        self._window_seconds = window_seconds
        self._timestamps = collections.deque()

    def add_event(self) -> None:
        self._timestamps.append(time.monotonic())
        self._evict_old()

    def count(self) -> int:
        self._evict_old()
        return len(self._timestamps)

    def _evict_old(self) -> None:
        cutoff = time.monotonic() - self._window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()