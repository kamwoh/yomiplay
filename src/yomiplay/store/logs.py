"""Per-session research log: JSONL events plus the screenshots they reference."""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path


class EventLog:
    def __init__(self, session_dir: Path):
        self.dir = session_dir
        (session_dir / "shots").mkdir(parents=True, exist_ok=True)
        self._f = (session_dir / "events.jsonl").open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def append(self, kind: str, **fields) -> None:
        with self._lock:
            rec = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "kind": kind, **fields}
            self._f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            self._f.flush()

    def save_png(self, png: bytes, frame_index: int) -> str:
        name = f"shot-{frame_index}.png"
        (self.dir / "shots" / name).write_bytes(png)
        return name

    def close(self) -> None:
        with self._lock:
            self._f.close()
