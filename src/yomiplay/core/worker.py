"""Subprocess entry point: owns exactly one Emulator and serves it over a Pipe."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from yomiplay.core.protocol import EmulatorError


@dataclass(frozen=True)
class EmulatorSpec:
    kind: Literal["fake", "libretro"]
    core_path: Path | None = None
    system_dir: Path | None = None
    save_dir: Path | None = None
    persist_saves: bool = True  # memory cards are written during play, never during replay verification


def build(spec: EmulatorSpec):
    if spec.kind == "fake":
        from yomiplay.core.fake import FakeEmulator
        return FakeEmulator()
    if spec.kind == "libretro":
        from yomiplay.core.emulator import LibretroEmulator
        if not (spec.core_path and spec.system_dir and spec.save_dir):
            raise EmulatorError("libretro spec needs core_path, system_dir and save_dir")
        return LibretroEmulator(spec.core_path, spec.system_dir, spec.save_dir, spec.persist_saves)
    raise EmulatorError(f"unknown emulator kind {spec.kind}")


PROPERTIES = {"frame_index", "provenance"}


def _refuse_all(conn, error: Exception) -> None:
    """The emulator could not be built: answer every request with that error until told to exit."""
    while True:
        try:
            method, _ = conn.recv()
        except EOFError:
            return
        if method == "__exit__":
            conn.send(("ok", None))
            return
        conn.send(("err", type(error).__name__, str(error)))


def serve(conn, spec: EmulatorSpec) -> None:
    try:
        emu = build(spec)
    except Exception as e:  # noqa: BLE001 - the parent must learn why, not just see the process die
        _refuse_all(conn, e)
        return
    while True:
        try:
            method, args = conn.recv()
        except EOFError:  # parent exited without "__exit__": still flush and unload
            emu.close()
            break
        if method == "__exit__":
            emu.close()
            conn.send(("ok", None))
            break
        try:
            value = getattr(emu, method) if method in PROPERTIES else getattr(emu, method)(*args)
            conn.send(("ok", value))
        except Exception as e:  # noqa: BLE001 - report every failure to the parent
            conn.send(("err", type(e).__name__, str(e)))
