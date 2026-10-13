"""Binary wire format for video/audio WebSocket messages, and audio-driven rate control."""
from __future__ import annotations

import struct

import numpy as np

from yomiplay.types import Frame

VIDEO = struct.Struct("<4sIHH")
AUDIO = struct.Struct("<4sII")


def encode_video(frame: Frame) -> bytes:
    rgba = np.ascontiguousarray(frame.rgba)
    return VIDEO.pack(b"VID1", frame.index, frame.width, frame.height) + rgba.tobytes()


def encode_audio(pcm: np.ndarray, frame_index: int) -> bytes:
    pcm = np.ascontiguousarray(pcm, dtype=np.int16)
    return AUDIO.pack(b"AUD1", frame_index, pcm.size // 2) + pcm.tobytes()


def decode_header(msg: bytes) -> tuple[str, int, int, int]:
    magic = msg[:4]
    if magic == b"VID1":
        _, idx, w, h = VIDEO.unpack_from(msg)
        return "VID1", idx, w, h
    if magic == b"AUD1":
        _, idx, n = AUDIO.unpack_from(msg)
        return "AUD1", idx, n, 0
    raise ValueError("unknown media message")


def rate_from_fill(fill_ms: float, target_ms: float = 80.0) -> float:
    err = (target_ms - fill_ms) / target_ms
    return 1.0 + max(-0.005, min(0.005, err * 0.005))
