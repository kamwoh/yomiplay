"""Seen words (automatic) and the notebook (starred) in one SQLite database."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (
  id INTEGER PRIMARY KEY, language TEXT NOT NULL, key TEXT NOT NULL, lemma TEXT NOT NULL, reading TEXT NOT NULL,
  pos TEXT NOT NULL DEFAULT '', meanings_json TEXT NOT NULL DEFAULT '{}', starred INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, seen_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE (language, key, reading));
CREATE TABLE IF NOT EXISTS encounters (
  id INTEGER PRIMARY KEY, word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  card_id TEXT NOT NULL, line_index INTEGER NOT NULL, line_text TEXT NOT NULL, session TEXT NOT NULL,
  frame_index INTEGER NOT NULL, screenshot TEXT NOT NULL, profile_name TEXT NOT NULL, profile_sha TEXT NOT NULL,
  provenance_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS enc_word ON encounters(word_id);
CREATE INDEX IF NOT EXISTS enc_line ON encounters(card_id, line_index);
"""


@dataclass(frozen=True)
class WordInput:
    language: str
    key: str
    lemma: str
    reading: str
    pos: str
    meanings: dict[str, str]


@dataclass(frozen=True)
class Encounter:
    card_id: str
    line_index: int
    line_text: str
    session: str
    frame_index: int
    screenshot: str
    profile_name: str
    profile_sha: str
    provenance_json: str


@dataclass(frozen=True)
class WordRow:
    id: int
    language: str
    lemma: str
    reading: str
    pos: str
    meanings: dict
    starred: bool
    seen_count: int
    first_seen: str
    last_seen: str


@dataclass(frozen=True)
class EncounterRow:
    line_text: str
    session: str
    frame_index: int
    screenshot: str
    profile_name: str
    created_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class WordStore:
    def __init__(self, db_path: Path):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()

    def record(self, words: list[WordInput], enc: Encounter) -> list[int]:
        with self._lock, self.db:
            ids, now = [], _now()
            for w in words:
                row = self.db.execute("SELECT id, meanings_json FROM words WHERE language=? AND key=? AND reading=?",
                                      (w.language, w.key, w.reading)).fetchone()
                if row is None:
                    cur = self.db.execute(
                        "INSERT INTO words (language, key, lemma, reading, pos, meanings_json, first_seen, last_seen)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (w.language, w.key, w.lemma, w.reading, w.pos, json.dumps(w.meanings, ensure_ascii=False),
                         now, now))
                    wid = cur.lastrowid
                else:
                    wid = row[0]
                    merged = {**json.loads(row[1]), **{k: v for k, v in w.meanings.items() if v}}
                    self.db.execute("UPDATE words SET meanings_json=?, last_seen=? WHERE id=?",
                                    (json.dumps(merged, ensure_ascii=False), now, wid))
                self.db.execute(
                    "INSERT INTO encounters (word_id, card_id, line_index, line_text, session, frame_index, screenshot,"
                    " profile_name, profile_sha, provenance_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (wid, enc.card_id, enc.line_index, enc.line_text, enc.session, enc.frame_index, enc.screenshot,
                     enc.profile_name, enc.profile_sha, enc.provenance_json, now))
                self.db.execute("UPDATE words SET seen_count = seen_count + 1 WHERE id=?", (wid,))
                ids.append(wid)
        return ids

    def clear_line(self, card_id: str, line_index: int) -> None:
        with self._lock, self.db:
            affected = [r[0] for r in self.db.execute(
                "SELECT DISTINCT word_id FROM encounters WHERE card_id=? AND line_index=?", (card_id, line_index))]
            self.db.execute("DELETE FROM encounters WHERE card_id=? AND line_index=?", (card_id, line_index))
            for wid in affected:
                self.db.execute("UPDATE words SET seen_count=(SELECT COUNT(*) FROM encounters WHERE word_id=?)"
                                " WHERE id=?", (wid, wid))
            self.db.execute("DELETE FROM words WHERE seen_count=0 AND starred=0")

    def star(self, word_id: int, starred: bool) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE words SET starred=? WHERE id=?", (1 if starred else 0, word_id))

    def list(self, filter: Literal["all", "starred", "session"] = "all", session: str | None = None,
             sort: Literal["count", "recent"] = "count", limit: int = 200) -> list[WordRow]:
        with self._lock:
            where, args = "", []
            if filter == "starred":
                where = "WHERE starred=1"
            elif filter == "session":
                where = "WHERE id IN (SELECT word_id FROM encounters WHERE session=?)"
                args.append(session or "")
            order = "seen_count DESC, last_seen DESC, id DESC" if sort == "count" else "last_seen DESC, id DESC"
            rows = self.db.execute(
                f"SELECT id, language, lemma, reading, pos, meanings_json, starred, seen_count, first_seen, last_seen"
                f" FROM words {where} ORDER BY {order} LIMIT ?", (*args, limit)).fetchall()
            return [WordRow(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), bool(r[6]), r[7], r[8], r[9]) for r in rows]

    def encounters(self, word_id: int) -> list[EncounterRow]:
        with self._lock:
            rows = self.db.execute("SELECT line_text, session, frame_index, screenshot, profile_name, created_at"
                                   " FROM encounters WHERE word_id=? ORDER BY id DESC", (word_id,)).fetchall()
            return [EncounterRow(*r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self.db.close()
