"""Frontend-managed save RAM (PS1 memory card 0 in Beetle PSX's default "libretro" card mode).

The core keeps the card in RETRO_MEMORY_SAVE_RAM; the frontend loads it after load_game and writes it
back when it changes. Writes go to a temp file and are renamed, so a crash never leaves half a card.
"""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path


class SaveRamFile:
    def __init__(self, path: Path):
        self.path = path
        self._last: bytes | None = None  # bytes as last restored or written

    def restore(self, ptr: int, size: int) -> bool:
        """Copy the file into the core's buffer (overlap only). Returns False if there is no file yet."""
        found = self.path.exists()
        if found:
            data = self.path.read_bytes()
            C.memmove(ptr, data, min(len(data), size))
        self._last = C.string_at(ptr, size)
        return found

    def flush(self, ptr: int, size: int) -> bool:
        """Write the buffer to disk if it changed since the last restore/flush. Returns True if written."""
        data = C.string_at(ptr, size)
        if data == self._last:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        self._last = data
        return True
