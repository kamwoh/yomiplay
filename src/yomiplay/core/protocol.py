"""The Emulator contract shared by live play (runtime), Gym env (later) and the subprocess proxy."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from yomiplay.types import AVInfo, InputState, MemRegion, Provenance, StepResult


class EmulatorError(RuntimeError):
    """Bad usage or bad content (not loaded, missing BIOS, out-of-range memory read...)."""


class EmulatorCrashed(RuntimeError):
    """The emulator process died; the instance is unusable."""


@runtime_checkable
class Emulator(Protocol):
    def load(self, content: Path, options: Mapping[str, str] | None = None) -> AVInfo: ...
    def step(self, inp: InputState, n_frames: int = 1, render: bool = True) -> StepResult: ...
    def read_memory(self, region: MemRegion, addr: int, size: int) -> bytes: ...
    def save_state(self) -> bytes: ...
    def load_state(self, blob: bytes) -> None: ...
    def reset(self) -> None: ...

    @property
    def frame_index(self) -> int: ...

    @property
    def provenance(self) -> Provenance: ...

    def close(self) -> None: ...
