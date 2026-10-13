"""Read the disc serial (e.g. SLPS-03002) from SYSTEM.CNF on a PS1 disc image."""
from __future__ import annotations

import re
import struct
from pathlib import Path

from yomiplay.core.content import cue_tracks

_BOOT_RE = re.compile(rb"BOOT\s*=\s*cdrom:\\?([A-Z]{4})_(\d{3})\.(\d{2})", re.IGNORECASE)


_MAX_READ = 64 * 1024
_TRACK_RE = re.compile(r"^\s*TRACK\s+\d+\s+(\S+)", re.IGNORECASE | re.MULTILINE)


class _Reader:
    def __init__(self, path: Path, sector: int, offset: int):
        self.f = path.open("rb")
        self.sector, self.offset = sector, offset

    def read(self, lba: int, size: int) -> bytes:
        """Read `size` bytes starting at sector `lba`; raises EOFError on truncated images."""
        if size > _MAX_READ:
            raise ValueError("read too large")
        out = bytearray()
        while len(out) < size:
            self.f.seek(lba * self.sector + self.offset)
            chunk = self.f.read(2048)
            if len(chunk) < 2048:
                raise EOFError("truncated image")
            out += chunk
            lba += 1
        return bytes(out[:size])


def _image(content: Path) -> tuple[Path, int, int] | None:
    if content.suffix.lower() == ".cue":
        tracks = cue_tracks(content)
        if not tracks or not tracks[0].exists():
            return None
        m = _TRACK_RE.search(content.read_text(errors="replace"))
        mode = m.group(1).upper() if m else ""
        if mode.startswith("MODE2"):
            return tracks[0], 2352, 24
        if mode.startswith("MODE1"):
            return tracks[0], 2352, 16
        return None
    if content.suffix.lower() == ".iso":
        return content, 2048, 0
    return None


def read_serial(content: Path) -> str | None:
    r: _Reader | None = None
    try:
        img = _image(content)
        if img is None:
            return None
        r = _Reader(*img)
        pvd = r.read(16, 2048)
        if pvd[1:6] != b"CD001":
            return None
        root = pvd[156:190]
        lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        buf = r.read(lba, min(size, _MAX_READ))
        i = 0
        while i < len(buf):
            n = buf[i]
            if n == 0:
                i = (i // 2048 + 1) * 2048
                continue
            if n < 34:
                return None
            rec = buf[i:i + n]
            name = rec[33:33 + rec[32]].split(b";")[0].upper()
            if name == b"SYSTEM.CNF":
                flba, fsize = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
                m = _BOOT_RE.search(r.read(flba, min(fsize, 2048)))
                if m:
                    return f"{m.group(1).decode().upper()}-{m.group(2).decode()}{m.group(3).decode()}"
                return None
            i += n
        return None
    except (OSError, EOFError, ValueError, IndexError, struct.error):
        return None
    finally:
        if r is not None:
            r.f.close()
