import time
from pathlib import Path

import pytest

from yomiplay.core.fake import FakeEmulator
from yomiplay.core.protocol import EmulatorCrashed
from yomiplay.runtime.clock import ManualClock, RealtimeClock
from yomiplay.runtime.inputs import HumanInput
from yomiplay.runtime.player import AudioReady, EmulatorFailed, FrameReady, Player, StatusChanged
from yomiplay.types import Button


def make(events, clock=None, emu=None):
    emu = emu or FakeEmulator()
    emu.load(Path("fake.cue"))
    inputs = HumanInput()
    p = Player(emu, clock or ManualClock(), inputs, events.append, fps=59.94)
    return p, inputs, emu


def test_run_frames_publishes_frame_and_audio():
    events = []
    p, inputs, _ = make(events)
    inputs.set_port(0, int(Button.START))
    p.run_frames(3)
    frames = [e for e in events if isinstance(e, FrameReady)]
    audio = [e for e in events if isinstance(e, AudioReady)]
    assert [f.frame.index for f in frames] == [1, 2, 3]
    assert len(audio) == 3 and audio[0].frame_index == 1
    assert p.latest_frame().index == 3


def test_thread_runs_pauses_and_resumes():
    events = []
    p, _, _ = make(events, clock=RealtimeClock())
    p.start()
    time.sleep(0.2)
    p.pause()
    n = p.latest_frame().index
    time.sleep(0.15)
    assert p.latest_frame().index == n
    p.resume()
    time.sleep(0.15)
    assert p.latest_frame().index > n
    p.stop()
    assert any(isinstance(e, StatusChanged) and e.paused for e in events)


def test_submit_runs_on_emulation_thread_even_when_paused():
    events = []
    p, _, _ = make(events, clock=RealtimeClock())
    p.start()
    p.pause()
    blob = p.submit(lambda emu: emu.save_state()).result(timeout=2)
    assert isinstance(blob, bytes)
    p.stop()


def test_crash_becomes_event_and_stops():
    class Crashy(FakeEmulator):
        def step(self, inp, n_frames=1, render=True):
            raise EmulatorCrashed("boom")

    events = []
    p, _, _ = make(events, clock=RealtimeClock(), emu=Crashy())
    p.start()
    time.sleep(0.1)
    p.stop()
    assert any(isinstance(e, EmulatorFailed) and "boom" in e.message for e in events)


def test_recorder_sees_input_changes_only():
    calls = []

    class Rec:
        def record(self, idx, inp):
            calls.append((idx, inp.port(0)))

        def checkpoint(self, idx, frame):
            pass

    events = []
    emu = FakeEmulator()
    emu.load(Path("fake.cue"))
    inputs = HumanInput()
    p = Player(emu, ManualClock(), inputs, events.append, fps=59.94, recorder=Rec())
    p.run_frames(2)
    inputs.set_port(0, 8)
    p.run_frames(2)
    assert calls == [(0, 0), (2, 8)]


def test_submit_after_stop_fails_fast():
    events = []
    p, _, _ = make(events, clock=RealtimeClock())
    p.start()
    p.stop()
    with pytest.raises(RuntimeError, match="not running"):
        p.submit(lambda emu: 1).result(timeout=1)


def test_submit_after_crash_fails_fast():
    class Crashy(FakeEmulator):
        def step(self, inp, n_frames=1, render=True):
            raise EmulatorCrashed("boom")

    events = []
    p, _, _ = make(events, clock=RealtimeClock(), emu=Crashy())
    p.start()
    time.sleep(0.1)
    with pytest.raises(RuntimeError, match="not running"):
        p.submit(lambda emu: 1).result(timeout=1)
    p.stop()
