"""Stop `yomiplay app` by itself when its browser tab is gone (used by the `app` command only, never by `serve`)."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable


class AutoShutdown:
    """Two timers on the event loop: a startup grace and an idle timer after the last media client leaves.

    `trigger(reason)` is called at most once, with "no_client" or "idle".
    """

    def __init__(self, idle_s: float, first_connect_s: float, trigger: Callable[[str], None]):
        self.idle_s = idle_s
        self.first_connect_s = first_connect_s
        self._trigger = trigger
        self._task: asyncio.Task | None = None
        self._fired = False
        self._closed = False

    def _arm(self, delay: float, reason: str) -> None:
        if self._closed:
            return
        self._cancel()
        self._task = asyncio.get_running_loop().create_task(self._after(delay, reason))

    async def _after(self, delay: float, reason: str) -> None:
        await asyncio.sleep(delay)
        if not self._fired:
            self._fired = True
            self._trigger(reason)

    def _cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    def start(self) -> None:
        """Server is up: wait for the first media client."""
        self._arm(self.first_connect_s, "no_client")

    def on_connect(self) -> None:
        self._cancel()

    def on_disconnect(self, remaining: int) -> None:
        if remaining == 0:
            self._arm(self.idle_s, "idle")

    async def close(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
