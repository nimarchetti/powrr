import json
import os
import time
import threading

import zmq
import paho.mqtt.client as mqtt

from state import DataStore, AppState, SENSORS, UIMode
from history import History
from renderer import render_live, render_graph

# ── Shared state ──────────────────────────────────────────────────────────────

data_store = DataStore()
app_state  = AppState()
history    = History()

_burst_until = 0.0
_burst_lock  = threading.Lock()


def _set_burst() -> None:
    global _burst_until
    with _burst_lock:
        _burst_until = time.time() + 1.0


def _is_burst() -> bool:
    with _burst_lock:
        return time.time() < _burst_until


# ── MQTT ──────────────────────────────────────────────────────────────────────

_SENSOR_IDS = [s["id"] for s in SENSORS]


def _on_connect(client, userdata, connect_flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"MQTT connect failed: {reason_code}")
        return
    for sid in _SENSOR_IDS:
        client.subscribe(f"homeassistant/sensor/{sid}/state")
        client.subscribe(f"homeassistant/sensor/{sid}/unit_of_measurement")
    print("MQTT connected and subscribed")


def _on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode("utf-8").strip()
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

                elif event == "MODE_INACTIVE" and msg.get("mode") == my_mode:
                    app_state.set_active(False)

                elif event == "ENCODER_DELTA":
                    _, _, active = app_state.snapshot()
                    if active:
                        app_state.step_index(msg.get("delta", 0))
                        _set_burst()

                elif event == "ENCODER_PUSH":
                    _, _, active = app_state.snapshot()
                    if active:
                        app_state.toggle_mode()
                        _set_burst()

            except Exception as exc:
                print(f"Event error: {exc}")

    threading.Thread(target=_loop, daemon=True).start()


# ── Frame publisher ───────────────────────────────────────────────────────────

_sequence = 0


def _send_frame(frame_socket, image) -> None:
    global _sequence
    header = json.dumps({
        "width":        image.width,
        "height":       image.height,
        "pixel_format": "L",
        "sequence":     _sequence,
        "timestamp_ms": int(time.time() * 1000),
    }).encode("utf-8")
    frame_socket.send_multipart([header, image.tobytes()])
    _sequence += 1


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    zmq_context  = zmq.Context()
    frame_socket = zmq_context.socket(zmq.PUSH)
    frame_socket.connect(os.environ["SWITCHRR_FRAME_ADDRESS"])

    _start_mqtt()
    _start_event_listener(zmq_context)

    print(f"powrr started — MODE_NAME={os.environ.get('MODE_NAME', 'powrr')}")

    while True:
        ui_mode, _, _ = app_state.snapshot()

        if ui_mode == UIMode.LIVE:
            img = render_live(data_store, app_state)
        else:
            img = render_graph(history, data_store, app_state)

        _send_frame(frame_socket, img)

        fps = 5 if _is_burst() else 1
        time.sleep(1.0 / fps)


if __name__ == "__main__":
    main()
