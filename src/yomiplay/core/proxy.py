"""EmulatorProxy: the Emulator protocol backed by a worker subprocess (one core per process)."""
from __future__ import annotations

import contextlib
import multiprocessing as mp
import threading
from collections.abc import Mapping
from pathlib import Path

from yomiplay.core.protocol import EmulatorCrashed, EmulatorError
from yomiplay.core.worker import EmulatorSpec, serve
from yomiplay.types import AVInfo, InputState, MemRegion, Provenance, StepResult

__all__ = ["EmulatorProxy", "EmulatorSpec"]
CLOSE_TIMEOUT_S = 3.0


class EmulatorProxy:
    def __init__(self, spec: EmulatorSpec):
        ctx = mp.get_context("spawn")
        self._conn, child = ctx.Pipe()
        self._proc = ctx.Process(target=serve, args=(child, spec), daemon=True, name="yomiplay-emulator")
        self._proc.start()
        child.close()
        self._closed = False
        self._lock = threading.Lock()  # one request/reply at a time across threads

    @property
    def pid(self) -> int:
        return self._proc.pid

    def _call(self, method: str, *args):
        if self._closed:
            raise EmulatorCrashed("emulator proxy is closed")
        try:
            with self._lock:
                self._conn.send((method, args))
                reply = self._conn.recv()
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError) as e:
            self._closed = True
            raise EmulatorCrashed(f"emulator process exited (code {self._proc.exitcode})") from e
        if reply[0] == "ok":
            return reply[1]
        _, kind, msg = reply
        raise EmulatorError(f"{kind}: {msg}")

    def load(self, content: Path, options: Mapping[str, str] | None = None) -> AVInfo:
        return self._call("load", content, dict(options or {}))

    def step(self, inp: InputState, n_frames: int = 1, render: bool = True) -> StepResult:
        return self._call("step", inp, n_frames, render)

    def read_memory(self, region: MemRegion, addr: int, size: int) -> bytes:
        return self._call("read_memory", region, addr, size)

    def save_state(self) -> bytes:
        return self._call("save_state")

    def load_state(self, blob: bytes) -> None:
        self._call("load_state", blob)

    def reset(self) -> None:
        self._call("reset")

    def set_game_serial(self, serial: str | None) -> None:
        try:
            self._call("set_game_serial", serial)
        except EmulatorError:
            pass  # emulators without serial support (fake) ignore it

    @property
    def frame_index(self) -> int:
        return self._call("frame_index")

    @property
    def provenance(self) -> Provenance:
        return self._call("provenance")

    def close(self) -> None:
        """Ask the worker to exit (it flushes memory cards); kill it if it does not answer in time.

        Safe to call more than once, after a crash, and while another thread is stuck in a call.
        """
        if not self._closed:
            self._closed = True  # new calls fail fast from here on
            answered = False
            if self._lock.acquire(timeout=CLOSE_TIMEOUT_S):
                try:
                    with contextlib.suppress(OSError, EOFError):  # worker already gone: nothing to ask
                        self._conn.send(("__exit__", ()))
                        if self._conn.poll(CLOSE_TIMEOUT_S):
                            self._conn.recv()
                            answered = True
                finally:
                    self._lock.release()
            if answered:
                self._proc.join(timeout=CLOSE_TIMEOUT_S)
        if self._proc.is_alive():
            self._proc.kill()
        self._proc.join(timeout=CLOSE_TIMEOUT_S)
