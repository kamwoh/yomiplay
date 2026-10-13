"""Frame pacing. RealtimeClock for play; ManualClock for tests and headless runs."""
from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def start(self, fps: float) -> None: ...
    def tick(self) -> None: ...
    def set_rate(self, factor: float) -> None: ...


class RealtimeClock:
    MAX_LAG_S = 0.25

    def __init__(self):
        self._period = 1 / 60
        self._next = 0.0
        self.rate = 1.0

    def start(self, fps: float) -> None:
        self._period = 1.0 / fps
        self._next = time.perf_counter() + self._period

    def set_rate(self, factor: float) -> None:
        self.rate = min(1.02, max(0.98, factor))

    def tick(self) -> None:
        now = time.perf_counter()
        if now - self._next > self.MAX_LAG_S:  # fell far behind (debugger, slow disk): resync, no catch-up burst
            self._next = now
        delay = self._next - now
        if delay > 0.002:
            time.sleep(delay - 0.001)
        while time.perf_counter() < self._next:
            pass
        self._next += self._period / self.rate


class ManualClock:
    def __init__(self):
        self.ticks = 0
        self.rate = 1.0

    def start(self, fps: float) -> None:
        self.ticks = 0

    def tick(self) -> None:
        self.ticks += 1

    def set_rate(self, factor: float) -> None:
        self.rate = factor
