"""Convert libretro framebuffers to RGBA (H x W x 4, uint8)."""
from __future__ import annotations

import numpy as np

FMT_0RGB1555, FMT_XRGB8888, FMT_RGB565 = 0, 1, 2


def to_rgba(raw: bytes, width: int, height: int, pitch: int, fmt: int) -> np.ndarray:
    buf = np.frombuffer(raw, dtype=np.uint8, count=pitch * height).reshape(height, pitch)
    out = np.empty((height, width, 4), np.uint8)
    out[..., 3] = 255
    if fmt == FMT_XRGB8888:
        px = buf[:, : width * 4].reshape(height, width, 4)
        out[..., 0] = px[..., 2]
        out[..., 1] = px[..., 1]
        out[..., 2] = px[..., 0]
        return out
    if fmt in (FMT_RGB565, FMT_0RGB1555):
        v = buf[:, : width * 2].copy().view("<u2").reshape(height, width).astype(np.uint32)
        if fmt == FMT_RGB565:
            r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
            out[..., 1] = (g * 255 + 31) // 63
        else:
            r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
            out[..., 1] = (g * 255 + 15) // 31
        out[..., 0] = (r * 255 + 15) // 31
        out[..., 2] = (b * 255 + 15) // 31
        return out
    raise ValueError(f"unsupported pixel format {fmt}")
