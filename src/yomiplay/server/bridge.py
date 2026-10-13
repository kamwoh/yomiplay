"""Hand-off from the Player thread to asyncio: latest frame wins, bounded audio, status fan-out."""
from __future__ import annotations

import asyncio

import numpy as np

from yomiplay.runtime.player import AudioReady, EmulatorFailed, FrameReady, PlayerEvent, StatusChanged
from yomiplay.types import Frame


class MediaBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, audio_capacity: int = 32):
        self.loop = loop
        self.latest: Frame | None = None
        self._frame_ev = asyncio.Event()
        self._audio: asyncio.Queue = asyncio.Queue(maxsize=audio_capacity)
        self._subs: set[asyncio.Queue] = set()

    # called on the Player thread
    def sink(self, event: PlayerEvent) -> None:
        if isinstance(event, FrameReady):
            self.latest = event.frame
            self.loop.call_soon_threadsafe(self._on_frame)
        elif isinstance(event, AudioReady):
            self.loop.call_soon_threadsafe(self._push_audio, event.pcm, event.frame_index)
        elif isinstance(event, (StatusChanged, EmulatorFailed)):
            self.loop.call_soon_threadsafe(self._fan_out, event)

    # event-loop side
    def _on_frame(self) -> None:
        ev, self._frame_ev = self._frame_ev, asyncio.Event()
        ev.set()

    def _push_audio(self, pcm: np.ndarray, idx: int) -> None:
        if self._audio.full():
            self._audio.get_nowait()  # drop oldest: a stalled client must never block the Player
        self._audio.put_nowait((pcm, idx))

    def clear_audio(self) -> None:
        """Drop queued audio (a new client must start near real time, not with a stale backlog)."""
        while not self._audio.empty():
            self._audio.get_nowait()

    def _fan_out(self, event) -> None:
        for q in list(self._subs):
            q.put_nowait(event)

    async def next_frame(self, after_index: int) -> Frame:
        while self.latest is None or self.latest.index <= after_index:
            await self._frame_ev.wait()
        return self.latest

    async def next_audio(self) -> tuple[np.ndarray, int]:
        return await self._audio.get()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)
