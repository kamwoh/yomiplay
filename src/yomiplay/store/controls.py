"""User key and gamepad bindings: <config_root>/controls.json overrides [keys.mapping] from config.toml."""
from __future__ import annotations

import json
import os
from pathlib import Path

BUTTONS = ["UP", "DOWN", "LEFT", "RIGHT", "CROSS", "CIRCLE", "SQUARE", "TRIANGLE",
           "L", "R", "L2", "R2", "L3", "R3", "SELECT", "START"]
# Standard Gamepad API layout: button index -> PS1 button (the analog stick still drives the D-pad)
DEFAULT_PAD = {0: "CROSS", 1: "CIRCLE", 2: "SQUARE", 3: "TRIANGLE", 4: "L", 5: "R", 6: "L2", 7: "R2",
               8: "SELECT", 9: "START", 10: "L3", 11: "R3", 12: "UP", 13: "DOWN", 14: "LEFT", 15: "RIGHT"}
MAX_PAD_INDEX = 31
MAX_KEY_CODE_LEN = 64


class InvalidControls(ValueError):
    pass


def validate(keys: object, pad: object) -> tuple[dict[str, str], dict[str, str]]:
    """Return clean (keys, pad) dicts or raise InvalidControls naming the first problem."""
    if not isinstance(keys, dict) or not isinstance(pad, dict):
        raise InvalidControls("keys and pad must be objects")
    clean_keys: dict[str, str] = {}
    for code, button in keys.items():
        if not isinstance(code, str) or not code.strip() or len(code) > MAX_KEY_CODE_LEN:
            raise InvalidControls(f"invalid key code {code!r}")
        if button not in BUTTONS:
            raise InvalidControls(f"unknown button {button!r} for key {code!r}")
        clean_keys[code] = button
    clean_pad: dict[str, str] = {}
    for index, button in pad.items():
        if not isinstance(index, str) or not index.isascii() or not index.isdigit() or int(index) > MAX_PAD_INDEX:
            raise InvalidControls(f"gamepad button index must be 0-{MAX_PAD_INDEX}, got {index!r}")
        if button not in BUTTONS:
            raise InvalidControls(f"unknown button {button!r} for gamepad button {index}")
        clean_pad[str(int(index))] = button
    return clean_keys, clean_pad


def default_pad() -> dict[str, str]:
    return {str(i): b for i, b in DEFAULT_PAD.items()}


def load(path: Path, config_keys: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Effective (keys, pad). A missing, unreadable or invalid file means the defaults."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate(data.get("keys", config_keys), data.get("pad", default_pad()))
    except (OSError, ValueError, AttributeError):
        return dict(config_keys), default_pad()


def save(path: Path, keys: dict[str, str], pad: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"keys": keys, "pad": pad}, indent=2), encoding="utf-8")
    os.replace(tmp, path)
