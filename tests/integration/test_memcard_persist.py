"""Memory card 0 (libretro SAVE_RAM) survives closing the emulator and starting a new process.

Each step runs in its own Python process: a libretro core can only be loaded once per process.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.rom

MAGIC = b"yomiplay-memcard-test"

PRELUDE = """
import ctypes as C, os, sys
from pathlib import Path
from yomiplay.core.emulator import LibretroEmulator
from yomiplay.types import InputState, MemRegion
MAGIC = b"yomiplay-memcard-test"
saves, mode = Path(sys.argv[1]), sys.argv[2]
emu = LibretroEmulator(Path(os.environ["YOMIPLAY_TEST_CORE"]), Path(os.environ["YOMIPLAY_TEST_BIOS_DIR"]), saves,
                       persist_saves=(mode != "nopersist"))
emu.load(Path(os.environ["YOMIPLAY_TEST_CONTENT"]))
"""

WRITE = PRELUDE + """
ptr, size = emu._core.memory(int(MemRegion.SAVE_RAM))
assert ptr and size >= 0x2000 + len(MAGIC), (ptr, size)
C.memmove(ptr + 0x1000, MAGIC, len(MAGIC))
emu.step(InputState(), n_frames=301 if mode == "periodic" else 1, render=False)
if mode == "periodic":
    os._exit(0)  # no close(): only the periodic flush may have written the file
emu.close()
"""

READ = PRELUDE + """
print(emu.read_memory(MemRegion.SAVE_RAM, 0x1000, len(MAGIC)) == MAGIC)
emu.close()
"""


def _run(script: str, saves: Path, mode: str) -> str:
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(script), str(saves), mode],
                       capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout.strip()


@pytest.mark.parametrize("mode", ["close", "periodic"])
def test_save_ram_persists_across_processes(tmp_path, mode):
    saves = tmp_path / "memcards"
    _run(WRITE, saves, mode)
    files = list(saves.glob("*.srm"))
    assert len(files) == 1 and MAGIC in files[0].read_bytes()
    assert _run(READ, saves, mode) == "True"


def test_persistence_disabled_writes_nothing(tmp_path):
    saves = tmp_path / "memcards"
    _run(WRITE, saves, "nopersist")
    assert not list(saves.glob("*.srm"))
    assert _run(READ, saves, "nopersist") == "False"
