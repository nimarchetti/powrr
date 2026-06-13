import json
import os
import time
import threading

import zmq
import paho.mqtt.client as mqtt

from state import DataStore, AppState, SENSORS, UIMode, SOC_SENSOR_ID
from history import History
from renderer import render_live, render_graph

# ── Shared state ──────────────────────────────────────────────────────────────

data_store = DataStore()
app_state  = AppState()
history    = History()

_render_wake = threading.Event()   # set by event thread to wake render loop immediately


def _wake_render() -> None:
    _render_wake.set()


# ── MQTT ──────────────────────────────────────────────────────────────────────

_SENSOR_IDS = [s["id"] for s in SENSORS]
_SOC_TOPIC  = f"homeassistant/sensor/{SOC_SENSOR_ID}/state"


def _on_connect(client, userdata, connect_flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"MQTT connect failed: {reason_code}")
        return
    for sid in _SENSOR_IDS:
        client.subscribe(f"homeassistant/sensor/{sid}/state")
        client.subscribe(f"homeassistant/sensor/{sid}/unit_of_measurement")
    client.subscribe(_SOC_TOPIC)
    print("MQTT connected and subscribed")


def _on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode("utf-8").strip()
    if topic == _SOC_TOPIC:
        try:
            data_store.set_soc(float(payload))
        except ValueError:
            pass
        return
    for sid in _SENSOR_IDS:
        if topic == f"homeassistant/sensor/{sid}/state":
            try:
                val = float(payload)
                data_store.set_value(sid, val)
                history.append(sid, val)
            except ValueError:
                pass
            return
        if topic == f"homeassistant/sensor/{sid}/unit_of_measurement":
            data_store.set_unit(sid, payload.strip('"'))
            return


def _start_mqtt() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    client.on_connect = _on_connect
    client.on_message = _on_message

    host = os.environ["MQTT_HOST"]
    port = int(os.environ.get("MQTT_PORT", 1883))

    def _loop():
        while True:
            try:
                client.connect(host, port, keepalive=60)
                client.loop_forever()
            except Exception as exc:
                print(f"MQTT error: {exc} — retrying in 5s")
                time.sleep(5)

    threading.Thread(target=_loop, daemon=True).start()


# ── ZeroMQ event listener ─────────────────────────────────────────────────────

def _start_event_listener(zmq_context: zmq.Context) -> None:
    my_mode = os.environ["MODE_NAME"]
    sock    = zmq_context.socket(zmq.SUB)
    sock.connect(os.environ["SWITCHRR_EVENT_ADDRESS"])
    sock.setsockopt(zmq.SUBSCRIBE, b"")

    def _loop():
        while True:
            try:
                msg   = json.loads(sock.recv())
                event = msg.get("event")

                if event == "MODE_ACTIVE" and msg.get("mode") == my_mode:
                    app_state.set_active(True)
                    _render_wake.set()   # start rendering at active rate immediately

                elif event == "MODE_INACTIVE" and msg.get("mode") == my_mode:
                    app_state.set_active(False)
                    _render_wake.set()   # wake so loop can switch to inactive rate

                elif event == "ENCODER_DELTA":
                    _, _, active = app_state.snapshot()
                    if active:
                        app_state.step_index(msg.get("delta", 0))
                        _wake_render()

                elif event == "ENCODER_PUSH":
                    _, _, active = app_state.snapshot()
                    if active:
                        app_state.toggle_mode()
                        _wake_render()

            except Exception as exc:
                print(f"Event error: {exc}")

    threading.Thread(target=_loop, daemon=True).start()


# ── Frame publisher ───────────────────────────────────────────────────────────

_sequence = 0


def _parse_display_sizes() -> list[tuple[int, int]]:
    """Return (width, height) pairs this mode should render for."""
    mode_name = os.environ.get("MODE_NAME", "powrr")
    raw = os.environ.get("DISPLAY_REGISTRY", "").strip()
    if raw:
        try:
            registry = json.loads(raw)
        except json.JSONDecodeError:
            pass
        else:
            sizes: list[tuple[int, int]] = []
            seen: set[tuple[int, int]] = set()
            for entry in registry:
                if any(m.get("mode_name") == mode_name for m in entry.get("modes", [])):
                    wh = (int(entry["width"]), int(entry["height"]))
                    if wh not in seen:
                        seen.add(wh)
                        sizes.append(wh)
            if sizes:
                return sizes
    w = int(os.environ.get("DISPLAY_WIDTH", "256"))
    h = int(os.environ.get("DISPLAY_HEIGHT", "64"))
    return [(w, h)]


def _send_frame(frame_socket, image, mode_name: str) -> None:
    global _sequence
    frame_socket.send_multipart([
        mode_name.encode(),
        str(image.width).encode(),
        str(image.height).encode(),
        image.tobytes(),
    ])
    _sequence += 1


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    zmq_context  = zmq.Context()
    frame_socket = zmq_context.socket(zmq.PUB)
    frame_socket.bind(os.environ["SWITCHRR_FRAME_BIND_ADDRESS"])

    _start_mqtt()
    _start_event_listener(zmq_context)

    mode_name    = os.environ.get("MODE_NAME", "powrr")
    display_sizes = _parse_display_sizes()
    print(f"powrr started — MODE_NAME={mode_name} sizes={display_sizes}")

    while True:
        ui_mode, _, _ = app_state.snapshot()

        for (w, h) in display_sizes:
            if ui_mode == UIMode.LIVE:
                img = render_live(data_store, app_state, w, h)
            else:
                img = render_graph(history, data_store, app_state, w, h)
            _send_frame(frame_socket, img, mode_name)

        _, _, active = app_state.snapshot()
        # Active: cap at 10 fps but wake instantly on any input.
        # Inactive: 1 fps — frames aren't shown, no point going faster.
        interval = 0.1 if active else 1.0
        _render_wake.wait(timeout=interval)
        _render_wake.clear()


if __name__ == "__main__":
    main()
