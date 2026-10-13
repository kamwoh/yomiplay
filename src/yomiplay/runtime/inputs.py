"""Where button presses come from: a human (browser), a script, later an agent."""
from __future__ import annotations

import threading
from typing import Protocol

from yomiplay.types import Frame, InputState


class InputSource(Protocol):
    def poll(self, obs: Frame | None) -> InputState | None:
        """Return the input for the next frame. None = no decision yet (lockstep clocks wait)."""
        ...


class HumanInput:
    def __init__(self, ports: int = 2):
        self._lock = threading.Lock()
        self._ports = [0] * ports

    def set_port(self, port: int, mask: int) -> None:
        with self._lock:
            if 0 <= port < len(self._ports):
                self._ports[port] = mask & 0xFFFF

    def poll(self, obs: Frame | None) -> InputState:
        with self._lock:
            return InputState(tuple(self._ports))


class ScriptedInput:
    def __init__(self, events: dict[int, InputState]):
        self._events = dict(events)
        self._n = 0
        self._current = InputState()

    def poll(self, obs: Frame | None) -> InputState:
        if self._n in self._events:
            self._current = self._events[self._n]
        self._n += 1
        return self._current
