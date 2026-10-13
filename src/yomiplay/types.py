"""Shared, picklable value types used by core, runtime, env and server."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum, IntFlag

import numpy as np


class Button(IntFlag):
    """Bit positions follow RETRO_DEVICE_ID_JOYPAD_* (libretro.h)."""
    B = 1 << 0
    Y = 1 << 1
    SELECT = 1 << 2
    START = 1 << 3
    UP = 1 << 4
    DOWN = 1 << 5
    LEFT = 1 << 6
    RIGHT = 1 << 7
    A = 1 << 8
    X = 1 << 9
    L = 1 << 10
    R = 1 << 11
    L2 = 1 << 12
    R2 = 1 << 13
    L3 = 1 << 14
    R3 = 1 << 15
    CROSS = B
    SQUARE = Y
    CIRCLE = A
    TRIANGLE = X


class MemRegion(IntEnum):
    SAVE_RAM = 0
    RTC = 1
    SYSTEM_RAM = 2
    VIDEO_RAM = 3


@dataclass(frozen=True)
class InputState:
    ports: tuple[int, ...] = (0, 0)

    def port(self, i: int) -> int:
        return self.ports[i] if i < len(self.ports) else 0


@dataclass(frozen=True, eq=False)
class Frame:
    index: int
    rgba: np.ndarray  # H x W x 4, uint8

    @property
    def width(self) -> int:
        return int(self.rgba.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgba.shape[0])


@dataclass(frozen=True, eq=False)
class StepResult:
    frame: Frame | None
    audio: np.ndarray  # int16, interleaved stereo


@dataclass(frozen=True)
class AVInfo:
    fps: float
    sample_rate: float
    base_w: int
    base_h: int


@dataclass(frozen=True)
class Provenance:
    core_sha256: str
    content_sha256: str
    core_options: dict[str, str] = field(default_factory=dict)
    game_serial: str | None = None
    libretro_api: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Provenance:
        return cls(**d)
