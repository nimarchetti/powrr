# powrr — Solar Mode Container: Implementation Plan

## Overview

A standalone Docker container subscribing to four Home Assistant MQTT sensors,
rendering solar power data to a 256×64 monochrome Pillow image, and pushing
frames to Switchrr via ZeroMQ per the mode container interface spec.

---

## Architecture

### Threads

1. **MQTT thread** (paho-mqtt, daemon) — subscribes to sensor topics, updates
   `DataStore` and `History`
2. **ZMQ event thread** (daemon) — receives encoder/lifecycle events from
   Switchrr
3. **Render loop** (main thread) — builds frames and publishes at 1 fps (5 fps
   burst for 1 second after any encoder input)

### ZeroMQ connections

| Socket | Direction | Env var |
|---|---|---|
| PUSH | container → Switchrr | `SWITCHRR_FRAME_ADDRESS` |
| SUB  | Switchrr → container | `SWITCHRR_EVENT_ADDRESS` |

---

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12-slim, pip install, `CMD main.py` |
| `docker-compose.yml` | All env vars; no exposed ports; no `--privileged` |
| `requirements.txt` | paho-mqtt, pyzmq, Pillow |
| `main.py` | Entry point: starts threads, render loop, `send_frame` |
| `state.py` | `DataStore`, `AppState` (thread-safe) |
| `history.py` | Per-sensor time-series ring buffer |
| `renderer.py` | `render_live` + `render_graph` PIL Image builders |

---

## Sensors

Encoder navigation cycles through these in order:

| Index | Label | MQTT sensor id |
|---|---|---|
| 0 | Solar | `pv_power_now` |
| 1 | Load | `inverter_load_power` |
| 2 | Feed In | `inverter_feed_in` |
| 3 | Grid | `inverter_grid_consumption` |

MQTT topics subscribed per sensor:
- `homeassistant/sensor/{id}/state`
- `homeassistant/sensor/{id}/unit_of_measurement`

Units are read dynamically from HA rather than hardcoded.

---

## State Machine

- **UI modes**: `LIVE` | `GRAPH`
- **selected_index**: 0–3 (wraps on encoder turn)
- `ENCODER_DELTA` → `step_index(delta)` (active only)
- `ENCODER_PUSH` → toggles UI mode (active only)
- `MODE_ACTIVE` / `MODE_INACTIVE` → sets `app_state.active`

Encoder events only processed when the mode is active per spec.

---

## Display Layouts

### Live view (256×64)

```
┌────────────────────────────────────────────────────────────────┐
│ Solar                                                          │  ← small label, y=1
│ 3.45 kW                                                        │  ← hero ~28pt, y=11
│ ─────────────────────────────────────────────────────────────  │  ← divider y=43
│ Load          Feed In        Grid                              │  ← small, y=45
│ 2.10 kW       0.80 kW        0.00 kW                          │  ← small, y=54
└────────────────────────────────────────────────────────────────┘
```

- `---` displayed for any sensor with no data yet

### Graph view (256×64)

```
┌────────────────────────────────────────────────────────────────┐
│ Solar  3.45 kW                                                 │  ← header y=1
│                        ╭╮                                      │
│                       ╭╯╰╮                                     │  ← line graph
│                  ╭────╯   ╰──                                  │    plot_top=12
│────────────────────────────────────────────────────────────────│  ← baseline y=62
└────────────────────────────────────────────────────────────────┘
```

- y axis auto-scaled to min/max within `GRAPH_WINDOW_SECONDS`
- "Waiting..." shown until ≥ 2 data points accumulated

---

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `SWITCHRR_FRAME_ADDRESS` | — | ZMQ PUSH address |
| `SWITCHRR_EVENT_ADDRESS` | — | ZMQ SUB address |
| `MODE_NAME` | — | Must match Switchrr's MODE_REGISTRY |
| `DISPLAY_WIDTH` | — | 256 for this display |
| `DISPLAY_HEIGHT` | — | 64 for this display |
| `MQTT_HOST` | — | Broker hostname/IP |
| `MQTT_PORT` | `1883` | |
| `MQTT_USERNAME` | — | |
| `MQTT_PASSWORD` | — | |
| `GRAPH_WINDOW_SECONDS` | `3600` | History window duration |
| `FONT_PATH` | *(unset)* | TTF path inside container; falls back to Pillow default |

---

## Font Configuration

Set `FONT_PATH` to a TTF path inside the container for a custom font.
Falls back to `ImageFont.load_default(size=N)` if unset or the file is missing.

To bundle a custom font:
1. Place the TTF in `fonts/` in this project
2. Uncomment the `COPY fonts/` line in `Dockerfile`
3. Set `FONT_PATH=/app/fonts/myfont.ttf` in `docker-compose.yml`

---

## Frame Rate Strategy

| Condition | Rate |
|---|---|
| Normal operation | 1 fps |
| 1 second after any encoder event | 5 fps burst |

Frames are published regardless of active state (per spec), ensuring zero
latency on mode switch. Container never stops publishing entirely.

---

## Verification Steps

1. `docker compose build` completes without errors
2. Run with a ZMQ stub (`PULL` + `PUB`) — confirm frames arrive at ~1 fps with
   correct `pixel_format: "L"` header JSON
3. `mosquitto_pub` a test value — confirm it appears in the next frame render
4. Inject `ENCODER_DELTA` event via PUB stub — `selected_index` cycles, frame
   rate bursts to 5 fps briefly
5. Inject `ENCODER_PUSH` — `ui_mode` toggles between `LIVE` and `GRAPH`
6. Let history accumulate for a few seconds — graph renders a polyline rather
   than "Waiting..."
