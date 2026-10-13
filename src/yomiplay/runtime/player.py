"""Player: drives one Emulator in real time on a dedicated thread and publishes frames and audio."""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Protocol, TypeVar

import numpy as np

from yomiplay.core.protocol import Emulator, EmulatorCrashed
from yomiplay.runtime.clock import Clock
from yomiplay.runtime.inputs import InputSource
from yomiplay.types import Frame, InputState

log = logging.getLogger("yomiplay.player")
T = TypeVar("T")


@dataclass(frozen=True)
class FrameReady:
    frame: Frame


@dataclass(frozen=True, eq=False)
class AudioReady:
    pcm: np.ndarray
    frame_index: int


@dataclass(frozen=True)
class StatusChanged:
    paused: bool


@dataclass(frozen=True)
class EmulatorFailed:
    message: str


PlayerEvent = FrameReady | AudioReady | StatusChanged | EmulatorFailed


class InputRecorder(Protocol):
    def record(self, frame_index: int, inp: InputState) -> None: ...
    def checkpoint(self, frame_index: int, frame: Frame) -> None: ...


class Player:
    def __init__(self, emu: Emulator, clock: Clock, inputs: InputSource,
                 sink: Callable[[PlayerEvent], None], fps: float, recorder: InputRecorder | None = None):
        self.emu, self.clock, self.inputs, self.sink, self.fps = emu, clock, inputs, sink, fps
        self.recorder = recorder
        self._jobs: queue.Queue[tuple[Callable, Future]] = queue.Queue()
        self._running = threading.Event()
        self._unpaused = threading.Event()
        self._unpaused.set()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._latest: Frame | None = None
        self._last_input: InputState | None = None
        self._frames_run = 0

    # ---- control (any thread) ----------------------------------------------------------------------
    def start(self) -> None:
        self.clock.start(self.fps)
        self._running.set()
        self._thread = threading.Thread(target=self._loop, name="yomiplay-player", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._unpaused.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._fail_pending_jobs()

    @property
    def paused(self) -> bool:
        return not self._unpaused.is_set()

    def pause(self) -> None:
        with self._state_lock:
            if not self.paused:
                self._unpaused.clear()
                self._await_loop_ack()
                self.sink(StatusChanged(True))

    def _await_loop_ack(self) -> None:
        """Block until the loop has passed a job drain, so no frame is in flight once pause() returns."""
        t = self._thread
        if t is None or not t.is_alive() or threading.current_thread() is t:
            return
        try:
            self.submit(lambda emu: None).result(timeout=1)
        except TimeoutError:  # loop wedged; pausing is still in effect
            log.warning("pause: emulation loop did not acknowledge")

    def resume(self) -> None:
        with self._state_lock:
            if self.paused:
                self.clock.start(self.fps)
                self._unpaused.set()
                self.sink(StatusChanged(False))

    def set_rate_hint(self, factor: float) -> None:
        self.clock.set_rate(factor)

    def latest_frame(self) -> Frame | None:
        return self._latest

    def submit(self, fn: Callable[[Emulator], T]) -> Future[T]:
        fut: Future = Future()
        if self._thread is None:  # not threaded (tests/headless): run inline
            self._run_job(fn, fut)
        elif not self._thread.is_alive():
            fut.set_exception(RuntimeError("player is not running"))
        else:
            self._jobs.put((fn, fut))
            if not self._thread.is_alive():  # loop exited inside the race window; nobody will drain
                self._fail_pending_jobs()
        return fut

    def _fail_pending_jobs(self) -> None:
        while True:
            try:
                _, fut = self._jobs.get_nowait()
            except queue.Empty:
                return
            if not fut.done():
                fut.set_exception(RuntimeError("player is not running"))

    # ---- emulation thread --------------------------------------------------------------------------
    def _run_job(self, fn, fut: Future) -> None:
        try:
            fut.set_result(fn(self.emu))
        except Exception as e:  # noqa: BLE001 - job errors travel to the caller via the Future
            fut.set_exception(e)

    def _drain_jobs(self) -> None:
        while True:
            try:
                fn, fut = self._jobs.get_nowait()
            except queue.Empty:
                return
            self._run_job(fn, fut)

    def _one_frame(self) -> None:
        inp = self.inputs.poll(self._latest)
        if inp is None:
            inp = self._last_input or InputState()
        if self.recorder is not None and inp != self._last_input:
            self.recorder.record(self._frames_run, inp)
        self._last_input = inp
        res = self.emu.step(inp)
        self._frames_run += 1
        if res.frame is not None:
            self._latest = res.frame
            self.sink(FrameReady(res.frame))
            if self.recorder is not None:
                self.recorder.checkpoint(self._frames_run, res.frame)
        self.sink(AudioReady(res.audio, self.emu.frame_index if res.frame is None else res.frame.index))

    def run_frames(self, n: int) -> None:
        for _ in range(n):
            self._drain_jobs()
            self._one_frame()

    def _loop(self) -> None:
        try:
            while self._running.is_set():
                self._drain_jobs()
                if not self._unpaused.is_set():
                    self._unpaused.wait(timeout=0.02)
                    continue
                self._one_frame()
                self.clock.tick()
        except EmulatorCrashed as e:
            log.error("emulator crashed: %s", e)
            self.sink(EmulatorFailed(str(e)))
        except Exception as e:  # unexpected: surface it, never die silently
            log.exception("player loop failed")
            self.sink(EmulatorFailed(f"{type(e).__name__}: {e}"))
        finally:
            self._drain_jobs()
