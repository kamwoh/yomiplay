import numpy as np
import pytest

from yomiplay.core.pixels import to_rgba


def test_xrgb8888_with_padding_pitch():
    w, h, pitch = 2, 2, 12  # 4 bytes of row padding
    raw = bytearray(pitch * h)
    raw[0:4] = bytes([0x10, 0x20, 0x30, 0x00])      # B G R X  -> (0x30,0x20,0x10)
    raw[pitch + 4:pitch + 8] = bytes([0xFF, 0, 0, 0])  # blue
    out = to_rgba(bytes(raw), w, h, pitch, 1)
    assert out.shape == (2, 2, 4)
    assert tuple(out[0, 0]) == (0x30, 0x20, 0x10, 255)
    assert tuple(out[1, 1]) == (0, 0, 0xFF, 255)


def test_rgb565_white_and_red():
    w, h, pitch = 2, 1, 4
    raw = np.array([0xFFFF, 0xF800], dtype="<u2").tobytes()
    out = to_rgba(raw, w, h, pitch, 2)
    assert tuple(out[0, 0]) == (255, 255, 255, 255)
    assert tuple(out[0, 1]) == (255, 0, 0, 255)


def test_0rgb1555_green():
    raw = np.array([0x03E0], dtype="<u2").tobytes()
    assert tuple(to_rgba(raw, 1, 1, 2, 0)[0, 0]) == (0, 255, 0, 255)


def test_unknown_format_rejected():
    with pytest.raises(ValueError):
        to_rgba(b"\0" * 4, 1, 1, 4, 9)
