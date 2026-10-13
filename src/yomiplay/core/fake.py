"""Deterministic stand-in for a real core. Used by unit tests and CI (no ROM, BIOS or core needed)."""
from __future__ import annotations

import pickle
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from yomiplay.core.protocol import EmulatorError
from yomiplay.types import AVInfo, Frame, InputState, MemRegion, Provenance, StepResult

RAM_SIZE = 2 * 1024 * 1024
SAMPLES_PER_FRAME = 735


class FakeEmulator:
    def __init__(self, width: int = 320, height: int = 240):
        self._w, self._h = width, height
        self._loaded = False
        self._t = 0          # game time (restored by load_state)
        self._index = 0      # frames executed by this instance
        self._ram = bytearray(RAM_SIZE)
        self._prov = Provenance(core_sha256="0" * 64, content_sha256="0" * 64, game_serial="FAKE-00000")

    def load(self, content: Path, options: Mapping[str, str] | None = None) -> AVInfo:
        self._loaded = True
        self._prov = Provenance(core_sha256="0" * 64, content_sha256="0" * 64,
                                core_options=dict(options or {}), game_serial="FAKE-00000")
        return AVInfo(59.94, 44100.0, self._w, self._h)

    def _require(self) -> None:
        if not self._loaded:
            raise EmulatorError("no content loaded")

    def step(self, inp: InputState, n_frames: int = 1, render: bool = True) -> StepResult:
        self._require()
        pad = inp.port(0) & 0xFFFF
        audio = []
        for _ in range(n_frames):
            self._t += 1
            self._index += 1
            self._ram[0:4] = (self._t & 0xFFFFFFFF).to_bytes(4, "little")
            self._ram[4:6] = pad.to_bytes(2, "little")
            ramp = (np.arange(SAMPLES_PER_FRAME * 2, dtype=np.int32) + self._t * 31) % 2000 - 1000
            audio.append(ramp.astype(np.int16))
        frame = None
        if render:
            rgba = np.empty((self._h, self._w, 4), np.uint8)
            rgba[..., 0] = (self._t * 3) & 0xFF
            rgba[..., 1] = pad & 0xFF
            rgba[..., 2] = (pad >> 8) & 0xFF
            rgba[..., 3] = 255
            rgba[(self._t // 4) % self._h, :, :3] = 255  # moving line so frames differ
            frame = Frame(self._index, rgba)
        return StepResult(frame, np.concatenate(audio))

    def read_memory(self, region: MemRegion, addr: int, size: int) -> bytes:
        self._require()
        if region != MemRegion.SYSTEM_RAM or addr < 0 or addr + size > RAM_SIZE:
            raise EmulatorError(f"memory read out of range: {region.name} {addr:#x}+{size}")
        return bytes(self._ram[addr:addr + size])

    def save_state(self) -> bytes:
        self._require()
        return pickle.dumps((self._t, bytes(self._ram)))

    def load_state(self, blob: bytes) -> None:
        self._require()
        self._t, ram = pickle.loads(blob)
        self._ram = bytearray(ram)

    def reset(self) -> None:
        """Like pressing the console's reset button: game time restarts, the frame counter keeps counting."""
        self._require()
        self._t = 0
        self._ram = bytearray(RAM_SIZE)

    @property
    def frame_index(self) -> int:
        return self._index

    @property
    def provenance(self) -> Provenance:
        return self._prov

    def close(self) -> None:
        self._loaded = False
