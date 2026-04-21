import os

from PIL import Image, ImageDraw, ImageFont

from state import SENSORS


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Load a font at the given pixel size.
    Uses FONT_PATH env var if set and the file exists; falls back to the
    Pillow built-in default font otherwise.
    """
    font_path = os.environ.get("FONT_PATH")
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)


def _fmt(value, unit) -> str:
    """Format a sensor reading for display, returning '---' when no data."""
    if value is None:
        return "---"
    unit_str = f" {unit}" if unit else ""
    return f"{value:.3f}{unit_str}"


def render_live(data_store, app_state) -> Image.Image:
    """
    Render the live values screen.

    Layout (256×64):
      - Top zone (~43px): selected sensor label + hero value
      - Divider line at y=43
      - Bottom strip (20px): other 3 sensors in equal columns
    """
    _, selected_index, _ = app_state.snapshot()
    width  = int(os.environ.get("DISPLAY_WIDTH",  256))
    height = int(os.environ.get("DISPLAY_HEIGHT",  64))

    img  = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)

    font_hero  = load_font(28)
    font_small = load_font(10)
    font_label = load_font(8)

    divider_y = height - 21   # leaves 21px for the bottom strip

    # ── Hero sensor ───────────────────────────────────────────────────────────
    selected = SENSORS[selected_index]
    value, unit = data_store.get(selected["id"])

    draw.text((2, 1),  selected["label"],       font=font_label, fill=200)
    draw.text((2, 11), _fmt(value, unit),        font=font_hero,  fill=255)

    # ── Divider ───────────────────────────────────────────────────────────────
    draw.line([(0, divider_y), (width - 1, divider_y)], fill=100)

    # ── Bottom strip — the other sensors ─────────────────────────────────────
    others    = [s for i, s in enumerate(SENSORS) if i != selected_index]
    col_width = width // len(others)

    for col, sensor in enumerate(others):
        x = col * col_width + 2
        v, u = data_store.get(sensor["id"])
        draw.text((x, divider_y + 2),  sensor["label"], font=font_label, fill=180)
        draw.text((x, divider_y + 11), _fmt(v, u),      font=font_small, fill=255)

    return img


def _fmt_age(seconds: float) -> str:
    """Format a positive number of seconds as a short age string, e.g. '-5m'."""
    s = int(abs(seconds))
    if s < 60:
        return f"-{s}s"
    m = s // 60
    if m < 60:
        return f"-{m}m"
    h, rem = divmod(m, 60)
    return f"-{h}h{rem}m" if rem else f"-{h}h"


def render_graph(history, data_store, app_state) -> Image.Image:
    """
    Render the graph screen for the selected sensor.

    Layout (256×64):
      - Header (11px):  sensor label + current value
      - Y-axis labels:  28px left margin; v_max near top, v_min near baseline
      - Plot area:      x=28..255, y=11..54
      - X-axis line:    y=54
      - X-axis labels:  y=55..63; oldest-point age at left, 'now' at right
      - 'Waiting...' shown until at least 2 data points exist
    """
    import time as _time

    _, selected_index, _ = app_state.snapshot()
    width    = int(os.environ.get("DISPLAY_WIDTH",          256))
    height   = int(os.environ.get("DISPLAY_HEIGHT",          64))
    window_s = float(os.environ.get("GRAPH_WINDOW_SECONDS", 3600))

    img  = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)

    font_small = load_font(10)
    font_label = load_font(8)
    font_axis  = load_font(7)

    sensor = SENSORS[selected_index]
    value, unit = data_store.get(sensor["id"])

    # ── Header ────────────────────────────────────────────────────────────────
    header = f"{sensor['label']}  {_fmt(value, unit)}"
    draw.text((2, 1), header, font=font_label, fill=255)

    # ── Layout constants ──────────────────────────────────────────────────────
    y_label_w   = 28          # px reserved on the left for y-axis labels
    x_label_h   = 10          # px reserved at the bottom for x-axis labels
    header_h    = 11

    plot_left   = y_label_w
    plot_right  = width - 1
    plot_top    = header_h
    plot_bottom = height - x_label_h - 1   # y=53 for a 64px display
    plot_w      = plot_right - plot_left
    plot_h      = plot_bottom - plot_top

    # ── Axes ──────────────────────────────────────────────────────────────────
    draw.line([(plot_left, plot_top),    (plot_left, plot_bottom)],  fill=80)   # y-axis
    draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill=80)   # x-axis

    points = history.get_window(sensor["id"], window_s)

    if len(points) < 2:
        msg  = "Waiting..."
        bbox = draw.textbbox((0, 0), msg, font=font_small)
        tw   = bbox[2] - bbox[0]
        draw.text(
            (plot_left + (plot_w - tw) // 2, plot_top + plot_h // 2 - 5),
            msg,
            font=font_small,
            fill=180,
        )
        return img

    times  = [p[0] for p in points]
    values = [p[1] for p in points]
    now    = _time.time()

    t_min, t_max = times[0], times[-1]
    v_min, v_max = min(0.0, min(values)), max(0.0, max(values))

    if t_max == t_min:
        t_max = t_min + 1
    if v_max == v_min:
        v_max += 0.5
    v_range = v_max - v_min

    def to_xy(t: float, v: float) -> tuple:
        x = plot_left + int((t - t_min) / (t_max - t_min) * plot_w)
        y = plot_bottom - int((v - v_min) / v_range * plot_h)
        return x, y

    coords = [to_xy(t, v) for t, v in points]
    draw.line(coords, fill=255, width=1)

    # ── Zero line (only when range spans both positive and negative) ─────────
    if v_min < 0 < v_max:
        _, zero_y = to_xy(t_min, 0.0)
        draw.line([(plot_left, zero_y), (plot_right, zero_y)], fill=120)

    # ── Y-axis labels (numeric only; unit is in the header) ───────────────────
    def fmt_val(v: float) -> str:
        return f"{v:.1f}" if abs(v) < 100 else f"{int(v)}"

    # v_max near the top of the plot
    draw.text((1, plot_top), fmt_val(v_max), font=font_axis, fill=160)

    # v_min just above the x-axis baseline
    min_lbl  = fmt_val(v_min)
    min_bbox = draw.textbbox((0, 0), min_lbl, font=font_axis)
    min_h    = min_bbox[3] - min_bbox[1]
    draw.text((1, plot_bottom - min_h), min_lbl, font=font_axis, fill=160)

    # ── X-axis labels: age of oldest point (left) and 'now' (right) ───────────
    age_lbl  = _fmt_age(now - t_min)
    draw.text((plot_left + 1, plot_bottom + 2), age_lbl, font=font_axis, fill=160)

    now_lbl  = "now"
    now_bbox = draw.textbbox((0, 0), now_lbl, font=font_axis)
    now_w    = now_bbox[2] - now_bbox[0]
    draw.text((plot_right - now_w, plot_bottom + 2), now_lbl, font=font_axis, fill=160)

    return img
