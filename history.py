import time
import threading

from state import SENSORS


class History:
    """Per-sensor in-memory ring buffer of (timestamp_s, value) tuples."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {s["id"]: [] for s in SENSORS}

    def append(self, sensor_id: str, value: float) -> None:
        ts = time.time()
        with self._lock:
            self._data[sensor_id].append((ts, value))

    def get_window(self, sensor_id: str, window_s: float) -> list:
        """Return all points within the last window_s seconds."""
        cutoff = time.time() - window_s
        with self._lock:
            return [(t, v) for t, v in self._data[sensor_id] if t >= cutoff]
