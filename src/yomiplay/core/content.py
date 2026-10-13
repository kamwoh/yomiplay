"""Locate the files behind a disc image and hash them for provenance."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_FILE_RE = re.compile(r'^\s*FILE\s+"([^"]+)"', re.IGNORECASE)


def cue_tracks(cue: Path) -> list[Path]:
    tracks = []
    for line in cue.read_text(errors="replace").splitlines():
        m = _FILE_RE.match(line)
        if m:
            tracks.append(cue.parent / m.group(1))
    return tracks


def _update(h, path: Path) -> None:
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    _update(h, path)
    return h.hexdigest()


def content_sha256(content: Path) -> str:
    h = hashlib.sha256()
    _update(h, content)
    if content.suffix.lower() == ".cue":
        for t in cue_tracks(content):
            _update(h, t)
    return h.hexdigest()
