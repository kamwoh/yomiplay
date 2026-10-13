"""Chat history across server sessions: ask/explain events from events.jsonl, newest sessions first, paged."""
from __future__ import annotations

import json
import re
from pathlib import Path

SESSION_RE = re.compile(r"^\d{8}-\d{6}$")
HISTORY_KINDS = {"ask", "explain"}
# EventLog writes '"kind": "<kind>"' verbatim, so a substring test skips the many other events (agent steps)
# without parsing them
WANTED = tuple(f'"kind": "{k}"' for k in (*HISTORY_KINDS, "correct_line"))
FIELDS = ("kind", "question", "answer", "card_id", "card", "shot", "ts")


def read_tag(path: Path) -> tuple[bool, str | None]:
    """Whether a session starts with a session_start event, and its serial. Reads only the first line."""
    try:
        with path.open(encoding="utf-8") as f:
            e = json.loads(f.readline())
    except (OSError, ValueError):
        return False, None
    if isinstance(e, dict) and e.get("kind") == "session_start":
        return True, e.get("serial")
    return False, None


def read_session(path: Path) -> list[dict]:
    """One session's ask/explain entries, oldest first, with later line corrections applied to their cards."""
    entries: list[dict] = []
    cards: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw in lines:
        if not any(w in raw for w in WANTED):
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue  # a half-written last line
        if not isinstance(e, dict):
            continue
        kind = e.get("kind")
        if kind in HISTORY_KINDS:
            entries.append({k: e[k] for k in FIELDS if k in e})
            if kind == "explain" and isinstance(e.get("card"), dict):
                cards[e.get("card_id")] = e["card"]
        elif kind == "correct_line":
            lines_ = (cards.get(e.get("card_id")) or {}).get("lines") or []
            if isinstance(e.get("line_index"), int) and 0 <= e["line_index"] < len(lines_):
                lines_[e["line_index"]]["source"] = e.get("text", "")
    return entries


def read_history(sessions_dir: Path, current: Path, serial: str | None, limit: int,
                 before: str | None = None) -> dict:
    """The newest `limit` entries older than `before`, oldest first.

    Sessions are read newest first: the current one, then the others by name. A session of another game
    (its session_start serial differs) is skipped; an untagged session (written before tags existed) is kept.
    `before` is the cursor from the previous page ("<session>:<index>"); the result's `before` is the cursor
    for the next older page, or None when there is nothing older. Raises ValueError on a bad cursor.
    """
    names = [current.name] + sorted(
        (d.name for d in sessions_dir.iterdir()
         if d.is_dir() and SESSION_RE.fullmatch(d.name) and d.name != current.name), reverse=True)
    start, end = 0, None
    if before is not None:
        name, _, idx = before.rpartition(":")
        if name not in names or not idx.isdigit():
            raise ValueError(f"bad history cursor: {before!r}")
        start, end = names.index(name), int(idx)
    out: list[dict] = []
    cursor = None
    for i in range(start, len(names)):
        name = names[i]
        path = sessions_dir / name / "events.jsonl"
        if name != current.name:
            tagged, sess_serial = read_tag(path)
            if tagged and sess_serial != serial:
                continue  # another game: skipped without reading the whole file
        entries = read_session(path)
        if i == start and end is not None:
            entries = entries[:end]
        for e in entries:
            e["session"] = name
        need = limit - len(out)
        if len(entries) >= need:
            cut = len(entries) - need
            out = entries[cut:] + out
            cursor = f"{name}:{cut}" if cut > 0 or i + 1 < len(names) else None
            break
        out = entries + out
    return {"session": current.name, "entries": out, "before": cursor}
