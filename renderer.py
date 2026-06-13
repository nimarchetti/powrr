import os

from PIL import Image, ImageDraw, ImageFont

from state import SENSORS

# ── Constants ─────────────────────────────────────────────────────────────────

BORDER   = 1
STRIP_H  = 24   # 2px top gap + 9pt label + 1px gap + 11pt value + 1px border buffer

COL_BG        = (0, 0, 0)
COL_WHITE     = (255, 255, 255)
COL_LABEL     = (160, 160, 160)
COL_AXIS      = (60, 60, 60)
COL_ZERO_LINE = (100, 100, 100)
COL_SOLAR     = (255, 220, 0)
COL_LOAD      = (210, 50, 50)
COL_FEED_IN   = (0, 200, 80)
COL_GRID      = (140, 140, 200)
COL_SOC_HIGH  = (0, 200, 80)
COL_SOC_MID   = (255, 165, 0)
COL_SOC_LOW   = (210, 50, 50)

_SENSOR_COLOURS = [COL_SOLAR, COL_LOAD, COL_FEED_IN, COL_GRID]


def _sensor_colour(sensor_index: int, value=None):
    if sensor_index == 4:  # Battery — positive=charging (green), negative=discharging (red)
        return COL_FEED_IN if (value or 0) >= 0 else COL_LOAD
    return _SENSOR_COLOURS[sensor_index] if sensor_index < len(_SENSOR_COLOURS) else COL_WHITE


def _soc_colour(soc: float):
    if soc > 75:
        return COL_SOC_HIGH
    if soc > 25:
        return COL_SOC_MID
    return COL_SOC_LOW


def load_font(size: int) -> ImageFont.FreeTypeFont:
    font_path = os.environ.get("FONT_PATH")
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)


def _fmt(value, unit) -> str:
    if value is None:
        return "---"
    unit_str = f" {unit}" if unit else ""
    return f"{value:.3f}{unit_str}"


def _draw_battery_live(draw, soc, font_label, divider_y) -> None:
    soc = max(0.0, min(100.0, soc))

    batt_x1, batt_x2 = 200, 244
    batt_y1 = BORDER + 2
    batt_h  = max(18, divider_y // 3)
    batt_y2 = batt_y1 + batt_h
    term_x1 = 244
    term_x2 = 248
    term_y1 = batt_y1 + batt_h // 3
    term_y2 = batt_y2 - batt_h // 3

    fill_col = _soc_colour(soc)

    draw.rectangle([batt_x1, batt_y1, batt_x2, batt_y2], outline=COL_LABEL)
    draw.rectangle([term_x1, term_y1, term_x2, term_y2],  outline=COL_LABEL)
    draw.rectangle([term_x1 + 1, term_y1 + 1, term_x2 - 1, term_y2 - 1], fill=COL_LABEL)

    fill_x1  = batt_x1 + 2
    fill_y1  = batt_y1 + 2
    fill_x2  = batt_x2 - 2
    fill_y2  = batt_y2 - 2
    filled_w = int(soc / 100.0 * (fill_x2 - fill_x1))
    if filled_w > 0:
        draw.rectangle([fill_x1, fill_y1, fill_x1 + filled_w, fill_y2], fill=fill_col)

    lbl  = f"{int(round(soc))}%"
    bbox = draw.textbbox((0, 0), lbl, font=font_label)
    lbl_w = bbox[2] - bbox[0]
    cx = (batt_x1 + term_x2) // 2
    draw.text((cx - lbl_w // 2, batt_y2 + 3), lbl, font=font_label, fill=COL_LABEL)


def _draw_soc_column(draw, soc, plot_top, plot_bottom, width) -> None:
    soc = max(0.0, min(100.0, soc))

    block_h  = 4
    gap      = 1
    box_x2   = width - 1 - BORDER          # right edge of outline box
    box_x1   = box_x2 - 9                  # 10px wide box (1+1+6+1+1)

    # White outline — represents 100% capacity
    draw.rectangle([box_x1, plot_top, box_x2, plot_bottom], outline=COL_WHITE)

    # Inner block area (1px gap inside outline on each side)
    inner_x1 = box_x1 + 2
    inner_x2 = box_x2 - 2
    inner_y1 = plot_top + 2
    inner_y2 = plot_bottom - 2
    inner_h  = inner_y2 - inner_y1 + 1

    N        = max(1, (inner_h + gap) // (block_h + gap))
    n_filled = round(soc / 100.0 * N)
    fill_col = _soc_colour(soc)

    for i in range(N):
        by2 = inner_y2 - i * (block_h + gap)
        by1 = by2 - block_h + 1
        if by1 < inner_y1:
            break
        if i < n_filled:
            draw.rectangle([inner_x1, by1, inner_x2, by2], fill=fill_col)


def render_live(data_store, app_state, width: int = 256, height: int = 64) -> Image.Image:
    B = BORDER
    _, selected_index, _ = app_state.snapshot()

    img  = Image.new("RGB", (width, height), COL_BG)
    draw = ImageDraw.Draw(img)

    font_hero  = load_font(28)
    font_small = load_font(11)
    font_label = load_font(9)

    divider_y = height - STRIP_H  # fixed strip height; hero area scales with display

    # ── Hero sensor ───────────────────────────────────────────────────────────
    selected = SENSORS[selected_index]
    value, unit = data_store.get(selected["id"])
    hero_col = _sensor_colour(selected_index, value)

    draw.text((2, B + 1),  selected["label"],  font=font_label, fill=COL_WHITE)
    draw.text((2, B + 10), _fmt(value, unit),   font=font_hero,  fill=hero_col)

    # ── Divider ───────────────────────────────────────────────────────────────
    draw.line([(B, divider_y), (width - 1 - B, divider_y)], fill=COL_AXIS)

    # ── Bottom strip — the other sensors ─────────────────────────────────────
    others    = [s for i, s in enumerate(SENSORS) if i != selected_index]
    col_width = width // len(others)

    for col, sensor in enumerate(others):
        x = col * col_width + 2
        v, u = data_store.get(sensor["id"])
        orig_idx = SENSORS.index(sensor)
        val_col = _sensor_colour(orig_idx, v)
        draw.text((x, divider_y + 2),  sensor["label"], font=font_label, fill=COL_WHITE)
        draw.text((x, divider_y + 12), _fmt(v, u),      font=font_small, fill=val_col)

    soc = data_store.get_soc()
    if soc is not None:
        _draw_battery_live(draw, soc, font_label, divider_y)

    return img


def _fmt_age(seconds: float) -> str:
    s = int(abs(seconds))
    if s < 60:
        return f"-{s}s"
    m = s // 60
    if m < 60:
        return f"-{m}m"
    h, rem = divmod(m, 60)
    return f"-{h}h{rem}m" if rem else f"-{h}h"


def render_graph(history, data_store, app_state, width: int = 256, height: int = 64) -> Image.Image:
    import time as _time

    B = BORDER
    _, selected_index, _ = app_state.snapshot()
    window_s = float(os.environ.get("GRAPH_WINDOW_SECONDS", 3600))

    img  = Image.new("RGB", (width, height), COL_BG)
    draw = ImageDraw.Draw(img)

    font_small = load_font(11)
    font_label = load_font(9)
    font_axis  = load_font(7)

    sensor = SENSORS[selected_index]
    value, unit = data_store.get(sensor["id"])
    col = _sensor_colour(selected_index, value)

    # ── Header ────────────────────────────────────────────────────────────────
    header = f"{sensor['label']}  {_fmt(value, unit)}"
    draw.text((2, B + 1), header, font=font_label, fill=COL_WHITE)

    # ── Layout constants ──────────────────────────────────────────────────────
    y_label_w   = 28
    x_label_h   = 10
    header_h    = 11

    plot_left   = y_label_w
    plot_right  = width - 16       # 10px SOC box + 3px margin + right edge
    plot_top    = header_h
    plot_bottom = height - x_label_h - 1
    plot_w      = plot_right - plot_left
    plot_h      = plot_bottom - plot_top

    # ── Axes ──────────────────────────────────────────────────────────────────
    draw.line([(plot_left, plot_top),    (plot_left, plot_bottom)],  fill=COL_AXIS)
    draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill=COL_AXIS)

    soc = data_store.get_soc()
    if soc is not None:
        _draw_soc_column(draw, soc, plot_top, plot_bottom, width)

    points = history.get_window(sensor["id"], window_s)

    if len(points) < 2:
        msg  = "Waiting..."
        bbox = draw.textbbox((0, 0), msg, font=font_small)
        tw   = bbox[2] - bbox[0]
        draw.text(
            (plot_left + (plot_w - tw) // 2, plot_top + plot_h // 2 - 5),
            msg,
            font=font_small,
            fill=COL_LABEL,
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
    draw.line(coords, fill=col, width=1)

    # ── Zero line (when range spans both positive and negative) ───────────────
    if v_min < 0 < v_max:
        _, zero_y = to_xy(t_min, 0.0)
        draw.line([(plot_left, zero_y), (plot_right, zero_y)], fill=COL_ZERO_LINE)

    # ── Y-axis labels ─────────────────────────────────────────────────────────
    def fmt_val(v: float) -> str:
        return f"{v:.1f}" if abs(v) < 100 else f"{int(v)}"

    draw.text((1, plot_top), fmt_val(v_max), font=font_axis, fill=COL_LABEL)

    min_lbl  = fmt_val(v_min)
    min_bbox = draw.textbbox((0, 0), min_lbl, font=font_axis)
    min_h    = min_bbox[3] - min_bbox[1]
    draw.text((1, plot_bottom - min_h), min_lbl, font=font_axis, fill=COL_LABEL)

    # ── X-axis labels ─────────────────────────────────────────────────────────
    age_lbl  = _fmt_age(now - t_min)
    draw.text((plot_left + 1, plot_bottom + 2), age_lbl, font=font_axis, fill=COL_LABEL)

    now_lbl  = "now"
    now_bbox = draw.textbbox((0, 0), now_lbl, font=font_axis)
    now_w    = now_bbox[2] - now_bbox[0]
    draw.text((plot_right - now_w, plot_bottom + 2), now_lbl, font=font_axis, fill=COL_LABEL)

    return img
