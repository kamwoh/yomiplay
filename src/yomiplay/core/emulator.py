"""LibretroEmulator: the real Emulator. Single-threaded, deterministic; run it inside worker.py."""
from __future__ import annotations

import ctypes as C
import hashlib
import logging
from collections.abc import Mapping
from pathlib import Path

from yomiplay.core.content import content_sha256, file_sha256
from yomiplay.core.libretro import LibretroCore
from yomiplay.core.pixels import to_rgba
from yomiplay.core.protocol import EmulatorError
from yomiplay.core.saveram import SaveRamFile
from yomiplay.types import AVInfo, Frame, InputState, MemRegion, Provenance, StepResult

# Known-good BIOS dumps (MD5) by file name. Users supply their own files.
KNOWN_BIOS_MD5 = {
    "scph5500.bin": "8dd7d5296a650fac7319bce665a6a53c",
    "scph5501.bin": "490f666e1afb15b7362b406ed1cea246",
    "scph5502.bin": "32736f17079d0b2b7024407c39bd3050",
}
SAVE_FLUSH_EVERY = 300  # frames (~5 s): how often changed save RAM is written to disk
log = logging.getLogger("yomiplay.core")


def check_bios(bios_dir: Path) -> list[str]:
    found = []
    for name, md5 in KNOWN_BIOS_MD5.items():
        p = bios_dir / name
        if p.exists() and hashlib.md5(p.read_bytes()).hexdigest() == md5:
            found.append(name)
    return found


class LibretroEmulator:
    def __init__(self, core_path: Path, system_dir: Path, save_dir: Path, persist_saves: bool = True):
        """persist_saves: load memory card 0 from save_dir and write it back (off for replay verification)."""
        self._core_path, self._system_dir, self._save_dir = core_path, system_dir, save_dir
        self._persist = persist_saves
        self._core: LibretroCore | None = None
        self._index = 0
        self._prov: Provenance | None = None
        self._sram: SaveRamFile | None = None
        self._next_flush = SAVE_FLUSH_EVERY

    def load(self, content: Path, options: Mapping[str, str] | None = None) -> AVInfo:
        if not check_bios(self._system_dir):
            raise EmulatorError(f"no known PS1 BIOS found in {self._system_dir} (expected e.g. scph5500.bin)")
        self._save_dir.mkdir(parents=True, exist_ok=True)
        core = LibretroCore(self._core_path, self._system_dir, self._save_dir, dict(options or {}))
        try:
            av = core.load_game(content)
            prov = Provenance(core_sha256=file_sha256(self._core_path), content_sha256=content_sha256(content),
                              core_options=core.option_values(), game_serial=None, libretro_api=core.api_version)
        except BaseException:
            core.close()
            raise
        self._core, self._prov = core, prov
        if self._persist:
            ptr, size = core.memory(MemRegion.SAVE_RAM)
            if ptr and size:
                self._sram = SaveRamFile(self._save_dir / f"{prov.content_sha256[:16]}.srm")
                self._sram.restore(ptr, size)
        return av

    def _flush_saves(self) -> None:
        if self._sram is None or self._core is None:
            return
        ptr, size = self._core.memory(MemRegion.SAVE_RAM)
        if ptr and size:
            try:
                self._sram.flush(ptr, size)
            except OSError as e:  # a full disk must not stop the game; try again next time
                log.error("could not write memory card %s: %s", self._sram.path, e)

    def set_game_serial(self, serial: str | None) -> None:
        if self._prov is not None:
            self._prov = Provenance(**{**self._prov.to_dict(), "game_serial": serial})

    def _require(self) -> LibretroCore:
        if self._core is None:
            raise EmulatorError("no content loaded")
        return self._core

    def step(self, inp: InputState, n_frames: int = 1, render: bool = True) -> StepResult:
        core = self._require()
        core.set_buttons(inp.ports)
        for i in range(n_frames):
            core.video_enabled = render and i == n_frames - 1
            core.run()
            self._index += 1
        if self._index >= self._next_flush:
            self._next_flush = self._index + SAVE_FLUSH_EVERY
            self._flush_saves()
        audio = core.take_audio()
        frame = None
        if render and core.last_video is not None:
            raw, w, h, pitch = core.last_video
            frame = Frame(self._index, to_rgba(raw, w, h, pitch, core.pixel_format))
        return StepResult(frame, audio)

    def read_memory(self, region: MemRegion, addr: int, size: int) -> bytes:
        ptr, total = self._require().memory(int(region))
        if not ptr or addr < 0 or size < 0 or addr + size > total:
            raise EmulatorError(f"memory read out of range: {region.name} {addr:#x}+{size} (size {total})")
        return C.string_at(ptr + addr, size)

    def save_state(self) -> bytes:
        return self._require().serialize()

    def load_state(self, blob: bytes) -> None:
        self._require().unserialize(blob)

    def reset(self) -> None:
        self._require().reset()

    @property
    def frame_index(self) -> int:
        return self._index

    @property
    def provenance(self) -> Provenance:
        if self._prov is None:
            raise EmulatorError("no content loaded")
        return self._prov

    def close(self) -> None:
        if self._core is not None:
            self._flush_saves()
            self._core.close()
            self._core = None
