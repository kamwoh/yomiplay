"""Prepare screenshots for the model: crop the dialogue area and enlarge it (small text reads better)."""
from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image


def png_bytes(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba[..., :3])).save(buf, format="PNG")
    return buf.getvalue()


def crop_box(rects: list[tuple[float, float, float, float]], w: int, h: int) -> tuple[int, int, int, int]:
    """Pixel box (x0, y0, x1, y1) the model sees: the union of the dialogue rects, or the whole screen."""
    if rects:
        x0 = min(r[0] for r in rects); y0 = min(r[1] for r in rects)
        x1 = max(r[0] + r[2] for r in rects); y1 = max(r[1] + r[3] for r in rects)
        box = (max(0, round(x0 * w)), max(0, round(y0 * h)), min(w, round(x1 * w)), min(h, round(y1 * h)))
        if box[2] > box[0] and box[3] > box[1]:
            return box
    return (0, 0, w, h)


def prepare_for_model(rgba: np.ndarray, rects: list[tuple[float, float, float, float]], scale: int = 3) -> bytes:
    h, w = rgba.shape[:2]
    img = Image.fromarray(np.ascontiguousarray(rgba[..., :3]))
    box = crop_box(rects, w, h)
    if box != (0, 0, w, h):
        img = img.crop(box)
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def box_to_screen(box: object, rects: list[tuple[float, float, float, float]], w: int, h: int) -> list[float] | None:
    """Model box [x, y, w, h] (0-1000 on the image it saw) -> full-screen fractions, clamped to that image.

    None when the box is malformed or nothing of it is left after clamping."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box):
        return None
    cx0, cy0, cx1, cy1 = crop_box(rects, w, h)
    cw, ch = cx1 - cx0, cy1 - cy0
    bx, by, bw, bh = (float(v) / 1000 for v in box)
    x0 = min(max(cx0 + bx * cw, cx0), cx1); x1 = min(max(cx0 + (bx + bw) * cw, cx0), cx1)
    y0 = min(max(cy0 + by * ch, cy0), cy1); y1 = min(max(cy0 + (by + bh) * ch, cy0), cy1)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return [round(x0 / w, 4), round(y0 / h, 4), round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)]
