from pathlib import Path

from yomiplay.core.fake import FakeEmulator
from yomiplay.runtime.clock import ManualClock
from yomiplay.runtime.inputs import HumanInput
from yomiplay.runtime.player import Player
from yomiplay.runtime.replay import Replay, ReplayRecorder, verify_replay
from yomiplay.types import InputState


def record_session(tmp_path):
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    emu.step(InputState(), n_frames=5)
    rec = ReplayRecorder(emu.save_state(), emu.provenance, fps=59.94, checkpoint_every=10)
    inputs = HumanInput()
    p = Player(emu, ManualClock(), inputs, lambda e: None, fps=59.94, recorder=rec)
    for i in range(60):
        inputs.set_port(0, (i // 7) * 3)
        p.run_frames(1)
    path = tmp_path / "s.ps1r"
    rec.save(path)
    return path


def test_round_trip_file(tmp_path):
    path = record_session(tmp_path)
    r = Replay.load(path)
    assert r.total_frames == 60 and r.fps == 59.94
    assert r.inputs[0][0] == 0 and len(r.inputs) == 9
    assert sorted(r.checkpoints) == [10, 20, 30, 40, 50, 60]


def test_verify_replay_passes_on_fresh_emulator(tmp_path):
    r = Replay.load(record_session(tmp_path))
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    assert verify_replay(emu, r) == []


def test_verify_replay_detects_divergence(tmp_path):
    r = Replay.load(record_session(tmp_path))
    # inputs[4] starts at frame 28, so it is live at the frame-30 checkpoint (inputs[3] is overridden before one)
    r.inputs[4] = (r.inputs[4][0], InputState((0xFFFF, 0)))
    emu = FakeEmulator(); emu.load(Path("fake.cue"))
    assert verify_replay(emu, r) != []
