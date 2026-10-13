"""Where user data and config live (Linux file system by default)."""
from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    env = os.environ.get("YOMIPLAY_DATA_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "yomiplay"


def config_root() -> Path:
    env = os.environ.get("YOMIPLAY_CONFIG_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "yomiplay"


class DataPaths:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _dir(self, *parts: str) -> Path:
        d = self.root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def words_db(self) -> Path:
        return self.root / "words.sqlite"

    def states_dir(self, serial: str) -> Path:
        return self._dir("states", serial)

    @property
    def memcards_dir(self) -> Path:
        return self._dir("memcards")

    @property
    def sessions_dir(self) -> Path:
        return self._dir("sessions")

    @property
    def shots_dir(self) -> Path:
        return self._dir("shots")
