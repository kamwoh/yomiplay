"""Configuration model. Loaded once by the composition root and passed down as sub-configs."""
from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from yomiplay.store.paths import config_root

DEFAULT_KEYS = {
    "ArrowUp": "UP", "ArrowDown": "DOWN", "ArrowLeft": "LEFT", "ArrowRight": "RIGHT",
    "KeyX": "CROSS", "KeyZ": "CIRCLE", "KeyS": "TRIANGLE", "KeyA": "SQUARE",
    "Enter": "START", "ShiftRight": "SELECT", "KeyQ": "L", "KeyW": "R", "Digit1": "L2", "Digit2": "R2",
}


class CoreConfig(BaseModel):
    core_path: Path | None = None
    bios_dir: Path | None = None
    options: dict[str, str] = Field(default_factory=dict)


class LibraryConfig(BaseModel):
    games_dir: Path | None = None


class LLMConfig(BaseModel):
    backend: str = "claude_cli"
    claude_bin: str = "claude"
    model: str | None = None
    timeout_s: float = 90.0


class CompanionConfig(BaseModel):
    pause_while_reading: bool = True
    default_profile: str = "ja-study"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class AppConfig(BaseModel):
    idle_shutdown_s: float = 10.0
    first_connect_timeout_s: float = 60.0


class KeyMap(BaseModel):
    mapping: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_KEYS))


class Config(BaseModel):
    core: CoreConfig = Field(default_factory=CoreConfig)
    library: LibraryConfig = Field(default_factory=LibraryConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    companion: CompanionConfig = Field(default_factory=CompanionConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    keys: KeyMap = Field(default_factory=KeyMap)


def load_config(path: Path | None = None) -> Config:
    path = path or (config_root() / "config.toml")
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        return Config.model_validate(tomllib.load(f))
