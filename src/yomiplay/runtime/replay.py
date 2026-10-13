"""Input replays: start state + frame-indexed input changes + periodic frame hashes."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from yomiplay.core.protocol import Emulator
from yomiplay.types import Frame, InputState, Provenance

MAGIC = b"PS1R"
VERSION = 1
REC = struct.Struct("<IHH")


def frame_hash(frame: Frame) -> str:
    return hashlib.sha256(frame.rgba.tobytes()).hexdigest()


@dataclass
class Replay:
    provenance: Provenance
    fps: float
    start_state: bytes
    inputs: list[tuple[int, InputState]]
    checkpoints: dict[int, str] = field(default_factory=dict)
    total_frames: int = 0

    def save(self, path: Path) -> None:
        header = json.dumps({"provenance": self.provenance.to_dict(), "fps": self.fps,
                             "total_frames": self.total_frames,
                             "checkpoints": {str(k): v for k, v in self.checkpoints.items()}}).encode()
        state = zlib.compress(self.start_state, 1)
        with path.open("wb") as f:
            f.write(MAGIC + struct.pack("<II", VERSION, len(header)) + header)
            f.write(struct.pack("<I", len(state)) + state)
            f.write(struct.pack("<I", len(self.inputs)))
            for off, inp in self.inputs:
                f.write(REC.pack(off, inp.port(0), inp.port(1)))

    @classmethod
    def load(cls, path: Path) -> Replay:
        data = path.read_bytes()
        if data[:4] != MAGIC:
            raise ValueError(f"{path} is not a yomiplay replay")
        version, hlen = struct.unpack_from("<II", data, 4)
        if version != VERSION:
            raise ValueError(f"unsupported replay version {version}")
        pos = 12
        header = json.loads(data[pos:pos + hlen]); pos += hlen
        (slen,) = struct.unpack_from("<I", data, pos); pos += 4
        state = zlib.decompress(data[pos:pos + slen]); pos += slen
        (n,) = struct.unpack_from("<I", data, pos); pos += 4
        inputs = []
        for _ in range(n):
            off, p0, p1 = REC.unpack_from(data, pos); pos += REC.size
            inputs.append((off, InputState((p0, p1))))
        return cls(Provenance.from_dict(header["provenance"]), header["fps"], state, inputs,
                   {int(k): v for k, v in header["checkpoints"].items()}, header["total_frames"])


class ReplayRecorder:
    def __init__(self, start_state: bytes, provenance: Provenance, fps: float, checkpoint_every: int = 60):
        self._replay = Replay(provenance, fps, start_state, [])
        self._every = checkpoint_every

    def record(self, frame_index: int, inp: InputState) -> None:
        self._replay.inputs.append((frame_index, inp))

    def checkpoint(self, frame_index: int, frame: Frame) -> None:
        self._replay.total_frames = frame_index
        if frame_index % self._every == 0:
            self._replay.checkpoints[frame_index] = frame_hash(frame)

    def save(self, path: Path) -> None:
        self._replay.save(path)


def verify_replay(emu: Emulator, replay: Replay) -> list[int]:
    """Re-run the replay from its start state; return frame offsets whose hash differs (empty = deterministic)."""
    emu.load_state(replay.start_state)
    changes = dict(replay.inputs)
    current = InputState()
    bad = []
    for off in range(replay.total_frames):
        current = changes.get(off, current)
        want = replay.checkpoints.get(off + 1)
        res = emu.step(current, render=want is not None)
        if want is not None and (res.frame is None or frame_hash(res.frame) != want):
            bad.append(off + 1)
    return bad
