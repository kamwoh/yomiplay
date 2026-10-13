import hashlib
from pathlib import Path

import numpy as np
import pytest

from yomiplay.core.fake import FakeEmulator
from yomiplay.core.protocol import Emulator, EmulatorError
from yomiplay.types import Button, InputState, MemRegion


def _hash(frames):
    h = hashlib.sha256()
    for f in frames:
        h.update(f.rgba.tobytes())
    return h.hexdigest()


def test_fake_implements_protocol():
    assert isinstance(FakeEmulator(), Emulator)


def test_step_advances_index_and_returns_audio():
    emu = FakeEmulator()
    emu.load(Path("fake.cue"))
    r = emu.step(InputState(), n_frames=3)
    assert emu.frame_index == 3 and r.frame.index == 3
    assert r.audio.dtype == np.int16 and r.audio.shape == (3 * 735 * 2,)
    assert r.frame.rgba.shape == (240, 320, 4)


def test_render_false_skips_frame():
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    assert emu.step(InputState(), render=False).frame is None


def test_input_changes_frames_and_ram():
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    a = emu.step(InputState((0, 0))).frame.rgba.copy()
    b = emu.step(InputState((int(Button.START), 0))).frame.rgba
    assert not np.array_equal(a, b)
    assert int.from_bytes(emu.read_memory(MemRegion.SYSTEM_RAM, 4, 2), "little") == int(Button.START)


def test_save_load_state_is_deterministic():
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    emu.step(InputState(), n_frames=10)
    blob = emu.save_state()
    inputs = [InputState(((i * 7) & 0xFFFF, 0)) for i in range(30)]
    run1 = [emu.step(i).frame for i in inputs]
    emu.load_state(blob)
    run2 = [emu.step(i).frame for i in inputs]
    assert _hash(run1) == _hash(run2)


def test_step_before_load_raises():
    with pytest.raises(EmulatorError):
        FakeEmulator().step(InputState())


def test_read_memory_bounds():
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    with pytest.raises(EmulatorError):
        emu.read_memory(MemRegion.SYSTEM_RAM, 2 * 1024 * 1024 - 1, 4)


def test_reset_restarts_game_time_but_not_the_frame_counter():
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    first = emu.step(InputState()).frame.rgba.copy()
    emu.step(InputState(), n_frames=9)
    emu.reset()
    again = emu.step(InputState())
    assert np.array_equal(again.frame.rgba, first)
    assert emu.frame_index == 11 and again.frame.index == 11  # frame indexes stay monotonic for the player
    assert int.from_bytes(emu.read_memory(MemRegion.SYSTEM_RAM, 0, 4), "little") == 1


def test_reset_needs_loaded_content():
    with pytest.raises(EmulatorError):
        FakeEmulator().reset()
