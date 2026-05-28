import threading
from enum import Enum


class UIMode(Enum):
    LIVE = "LIVE"
    GRAPH = "GRAPH"


SENSORS = [
    {"id": "pv_power_now",              "label": "Solar"},
    {"id": "inverter_load_power",       "label": "Load"},
    {"id": "inverter_feed_in",          "label": "Feed In"},
    {"id": "inverter_grid_consumption", "label": "Grid"},
    {"id": "battery_power",             "label": "Battery"},
]

SOC_SENSOR_ID = "inverter_battery_soc"


class DataStore:
    """Thread-safe store for current sensor values and units."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {s["id"]: {"value": None, "unit": None} for s in SENSORS}
        self._soc = None

    def set_value(self, sensor_id: str, value: float) -> None:
        with self._lock:
            self._data[sensor_id]["value"] = value

    def set_unit(self, sensor_id: str, unit: str) -> None:
        with self._lock:
            self._data[sensor_id]["unit"] = unit

    def get(self, sensor_id: str) -> tuple:
        with self._lock:
            d = self._data[sensor_id]
            return d["value"], d["unit"]

    def set_soc(self, value: float) -> None:
        with self._lock:
            self._soc = value

    def get_soc(self) -> "float | None":
        with self._lock:
            return self._soc


class AppState:
    """Thread-safe UI state: current mode and selected sensor index."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ui_mode = UIMode.LIVE
        self._selected_index = 0
        self._active = True

    def toggle_mode(self) -> None:
        with self._lock:
            self._ui_mode = (
                UIMode.GRAPH if self._ui_mode == UIMode.LIVE else UIMode.LIVE
            )

    def step_index(self, delta: int) -> None:
        with self._lock:
            self._selected_index = (self._selected_index + delta) % len(SENSORS)

    def set_active(self, value: bool) -> None:
        with self._lock:
            self._active = value

    def snapshot(self) -> tuple:
        """Return (ui_mode, selected_index, active) atomically."""
        with self._lock:
            return self._ui_mode, self._selected_index, self._active
