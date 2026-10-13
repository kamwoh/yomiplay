"""Game profiles: our own measurements and hints for a specific disc (no game content)."""
from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class GameProfileError(ValueError):
    """A game profile file exists but cannot be used; the message names the file."""


class GameProfile(BaseModel):
    name: str
    language: str = "ja"
    dialogue_rects: list[tuple[float, float, float, float]] = Field(default_factory=list)  # x, y, w, h fractions
    prompt_hints: str = ""
    core_options: dict[str, str] = Field(default_factory=dict)
    ram: dict[str, dict] = Field(default_factory=dict)


def load_profile(serial: str | None, search_dirs: list[Path]) -> GameProfile:
    """First match wins: <serial>.toml in each dir in order, then _default.toml. Put the user's dir first."""
    names = ([f"{serial}.toml"] if serial else []) + ["_default.toml"]
    for name in names:
        for d in search_dirs:
            p = d / name
            if p.exists():
                try:
                    with p.open("rb") as f:
                        return GameProfile.model_validate(tomllib.load(f))
                except (OSError, tomllib.TOMLDecodeError, ValidationError) as e:
                    raise GameProfileError(f"bad game profile {p}: {e}") from e
    return GameProfile(name="Unknown game")
