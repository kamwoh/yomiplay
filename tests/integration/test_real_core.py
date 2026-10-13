import hashlib
import os
from pathlib import Path

import pytest

from yomiplay.core.emulator import LibretroEmulator
from yomiplay.types import InputState, MemRegion

pytestmark = pytest.mark.rom


def _emu(tmp_path):
    return LibretroEmulator(Path(os.environ["YOMIPLAY_TEST_CORE"]), Path(os.environ["YOMIPLAY_TEST_BIOS_DIR"]),
                            tmp_path / "saves")


def test_boots_and_is_deterministic(tmp_path):
    emu = _emu(tmp_path)
    av = emu.load(Path(os.environ["YOMIPLAY_TEST_CONTENT"]))
    assert 59 < av.fps < 61 and av.sample_rate == 44100
    r = emu.step(InputState(), n_frames=600)
    assert r.frame is not None and r.frame.rgba.shape[2] == 4
    assert 600 * 700 * 2 < r.audio.size < 600 * 770 * 2
    assert len(emu.read_memory(MemRegion.SYSTEM_RAM, 0, 16)) == 16
    # Quirk: the first restore of a state saved mid disc read (~frame 600) replays differently.
    # Snapshot only after the boot/CD-load phase settles: a state saved at ~frame 600 (mid disc read) replays
    # differently on its first restore (core quirk, see task-5 report); settled states are exact from the first load.
    emu.step(InputState(), n_frames=1200, render=False)
    blob = emu.save_state()

    def run():
        emu.load_state(blob)
        h = hashlib.sha256()
        for _ in range(120):
            h.update(emu.step(InputState()).frame.rgba.tobytes())
        return h.hexdigest()

    assert run() == run()
    emu.close()


def test_reset_restarts_the_game(tmp_path):
    emu = _emu(tmp_path)
    emu.load(Path(os.environ["YOMIPLAY_TEST_CONTENT"]))
    emu.step(InputState(), n_frames=900, render=False)
    ram_before = emu.read_memory(MemRegion.SYSTEM_RAM, 0x10000, 4096)
    emu.reset()
    after_reset = emu.step(InputState(), n_frames=1)
    assert after_reset.frame is not None and emu.frame_index == 901  # keeps counting; the console restarts
    emu.step(InputState(), n_frames=900, render=False)
    # booting again from power-on reaches the same place deterministically: the console really restarted
    assert emu.read_memory(MemRegion.SYSTEM_RAM, 0x10000, 4096) == ram_before
    emu.close()
