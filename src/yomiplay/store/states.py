"""Numbered save-state slots with thumbnails and provenance sidecars."""
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from yomiplay.types import Frame, Provenance

SLOTS = range(1, 10)


class StateMismatch(Exception):
    """The slot was saved with a different core or game."""


class SlotCorrupt(Exception):
    """The slot's files are missing, malformed, or corrupted."""


@dataclass(frozen=True)
class SlotInfo:
    slot: int
    frame_index: int
    saved_at: str
    has_thumb: bool


class StateStore:
    def __init__(self, directory: Path):
        self.dir = directory
        directory.mkdir(parents=True, exist_ok=True)

    def _p(self, slot: int, ext: str) -> Path:
        if slot not in SLOTS:
            raise ValueError(f"slot must be 1-9, got {slot}")
        return self.dir / f"slot-{slot}.{ext}"

    def thumb_path(self, slot: int) -> Path:
        return self._p(slot, "png")

    def put(self, slot: int, blob: bytes, frame: Frame, prov: Provenance) -> SlotInfo:
        state_p = self._p(slot, "state")
        json_p = self._p(slot, "json")
        png_p = self._p(slot, "png")

        # Delete any existing sidecar before starting to avoid stale provenance
        json_p.unlink(missing_ok=True)

        # Write state file via temp + rename for atomicity
        state_tmp = state_p.with_suffix(".tmp")
        state_tmp.write_bytes(zlib.compress(blob, 1))
        state_tmp.replace(state_p)

        # Write thumbnail
        img = Image.fromarray(frame.rgba[..., :3])
        img.thumbnail((160, 120))
        img.save(png_p)

        # Write sidecar last via temp + rename for atomicity
        meta = {"frame_index": frame.index, "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "provenance": prov.to_dict()}
        json_tmp = json_p.with_suffix(".tmp")
        json_tmp.write_text(json.dumps(meta))
        json_tmp.replace(json_p)

        return SlotInfo(slot, frame.index, meta["saved_at"], True)

    def get(self, slot: int, expect: Provenance) -> bytes:
        state_p = self._p(slot, "state")
        json_p = self._p(slot, "json")

        # Slot is empty only if .state file doesn't exist
        if not state_p.exists():
            raise FileNotFoundError(f"slot {slot} is empty")

        # Check for sidecar; .state without .json is corrupt
        if not json_p.exists():
            raise SlotCorrupt(f"slot {slot}: state file exists but sidecar is missing")

        # Read and validate sidecar
        try:
            meta = json.loads(json_p.read_text())
            saved = Provenance.from_dict(meta["provenance"])
        except (json.JSONDecodeError, KeyError) as e:
            raise SlotCorrupt(f"slot {slot}: sidecar is malformed or missing provenance") from e

        # Check provenance
        if (saved.core_sha256, saved.content_sha256) != (expect.core_sha256, expect.content_sha256):
            raise StateMismatch(f"slot {slot} was saved with a different core or game")

        # Decompress state
        try:
            return zlib.decompress(state_p.read_bytes())
        except zlib.error as e:
            raise SlotCorrupt(f"slot {slot}: state file is corrupted or truncated") from e

    def list(self) -> list[SlotInfo]:
        out = []
        for slot in SLOTS:
            j = self.dir / f"slot-{slot}.json"
            if j.exists():
                try:
                    meta = json.loads(j.read_text())
                    out.append(SlotInfo(slot, meta["frame_index"], meta["saved_at"], self.thumb_path(slot).exists()))
                except (json.JSONDecodeError, KeyError):
                    # Skip slots with malformed sidecars
                    pass
        return out
