"""Model and thinking choice per use (now only "chat"): <config_root>/llm.json overrides config.toml."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

TARGETS = ("chat",)
# None means "the claude CLI default". Aliases always resolve to the newest model of that family.
MODELS = [None, "opus", "sonnet", "haiku", "fable"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
THINKING = [None, "off", *EFFORTS]  # "off" sets MAX_THINKING_TOKENS=0 (Opus may still think a little)
FULL_MODEL_ID = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]{0,63}$")  # e.g. a full id from config.toml
_save_lock = threading.Lock()


class InvalidChoice(ValueError):
    pass


def validate(model: object, thinking: object) -> dict:
    if model not in MODELS and not (isinstance(model, str) and FULL_MODEL_ID.match(model)):
        raise InvalidChoice(f"unknown model {model!r}")
    if thinking not in THINKING:
        raise InvalidChoice(f"unknown thinking level {thinking!r}")
    return {"model": model, "thinking": thinking}


def load(path: Path, defaults: dict[str, dict]) -> dict[str, dict]:
    """Effective choice per target. A missing, unreadable or invalid entry means that target's default."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = {}
    for t in TARGETS:
        try:
            entry = data[t]
            out[t] = validate(entry.get("model"), entry.get("thinking"))
        except (KeyError, TypeError, AttributeError, InvalidChoice):
            out[t] = dict(defaults[t])
    return out


def save(path: Path, target: str, choice: dict) -> None:
    """Store one target's choice. Other targets keep their entry (or keep following config.toml)."""
    with _save_lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[target] = choice
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
