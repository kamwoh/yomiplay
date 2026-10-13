"""Explain profiles: user-editable TOML files that set languages, level and style."""
from __future__ import annotations

import hashlib
import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("yomiplay.assist")


class ExplainProfile(BaseModel):
    name: str
    title: str = ""
    source_language: str = "ja"
    target_languages: list[str] = Field(default_factory=lambda: ["en"], min_length=1)
    level: str = "beginner"
    style: str = ""
    card: Literal["study", "free"] = "study"


@dataclass(frozen=True)
class ProfileRef:
    name: str
    sha256: str


class ProfileLibrary:
    def __init__(self, dirs: list[Path]):
        self.dirs = dirs
        self._problems: list[str] = []

    def _load_all(self) -> dict[str, ExplainProfile]:
        """Read every profile file; invalid files are skipped and listed in problems()."""
        found: dict[str, ExplainProfile] = {}
        problems: list[str] = []
        for d in self.dirs:  # later directories override earlier ones
            if not d.exists():
                continue
            for f in sorted(d.glob("*.toml")):
                try:
                    with f.open("rb") as fh:
                        p = ExplainProfile.model_validate(tomllib.load(fh))
                except (OSError, tomllib.TOMLDecodeError, ValidationError) as e:
                    detail = e.errors()[0] if isinstance(e, ValidationError) else e
                    msg = f"{f}: {detail['loc'][0]}: {detail['msg']}" if isinstance(detail, dict) else f"{f}: {e}"
                    log.warning("skipping explain profile %s", msg)
                    problems.append(msg)
                    continue
                found[p.name] = p
        self._problems = problems
        return found

    def problems(self) -> list[str]:
        """Files that could not be used, as of the last read ("<path>: <reason>")."""
        self._load_all()
        return list(self._problems)

    def list(self) -> list[ExplainProfile]:
        return [p for _, p in sorted(self._load_all().items())]

    def get(self, name: str) -> ExplainProfile:
        return self._load_all()[name]

    def ref(self, profile: ExplainProfile) -> ProfileRef:
        from yomiplay.assist.prompts import PROMPT_VERSION
        digest = hashlib.sha256((PROMPT_VERSION + profile.model_dump_json()).encode()).hexdigest()
        return ProfileRef(profile.name, digest)
