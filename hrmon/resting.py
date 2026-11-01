"""Resting heart rate: the lowest average over any steady 3-minute window."""

from collections import deque

WINDOW_SECONDS = 180
MIN_COVERAGE = 0.9  # window must span at least 90% of WINDOW_SECONDS
MAX_GAP_SECONDS = 6  # any longer gap in the data invalidates the window


class RestingHeartRate:
    def __init__(self, initial: int | None = None):
        self.value = initial
        self._window = deque()  # (time, bpm)
        self._sum = 0

    def add(self, t: float, bpm: int) -> bool:
        """Add a sample; returns True if the resting value changed."""
        if self._window and t - self._window[-1][0] > MAX_GAP_SECONDS:
            self.reset_window()
        self._window.append((t, bpm))
        self._sum += bpm
        while t - self._window[0][0] > WINDOW_SECONDS:
            self._sum -= self._window.popleft()[1]

        if t - self._window[0][0] < WINDOW_SECONDS * MIN_COVERAGE:
            return False
        avg = round(self._sum / len(self._window))
        if self.value is None or avg < self.value:
            self.value = avg
            return True
        return False

    def reset_window(self):
        self._window.clear()
        self._sum = 0
