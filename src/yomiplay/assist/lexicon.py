"""Split Japanese text into dictionary-form words locally (fugashi + UniDic Lite)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SKIP_POS = {"助詞", "助動詞", "補助記号", "記号", "空白"}


@dataclass(frozen=True)
class Token:
    surface: str
    lemma: str     # dictionary form as usually written (見つける)
    key: str       # canonical lemma used for de-duplication (見付ける)
    reading: str   # hiragana reading of the dictionary form
    pos: str


class Tokenizer(Protocol):
    language: str

    def tokenize(self, text: str) -> list[Token]: ...


def _hira(kata: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in kata)


def _has_kanji(s: str) -> bool:
    return any("一" <= c <= "鿿" or c == "々" for c in s)


class FugashiTokenizer:
    """UniDic facts (verified): `lemma` is canonical and usually kanji (あそぼう -> 遊ぶ, あした -> 明日);
    `orthBase` keeps the written script (あそぶ, 見つける); loanword lemmas carry a tag ("ボマー-bomber");
    unknown words (e.g. Latin text) have lemma None."""

    language = "ja"

    def __init__(self):
        from fugashi import Tagger
        self._tagger = Tagger()

    def tokenize(self, text: str) -> list[Token]:
        out = []
        for w in self._tagger(text):
            f = w.feature
            pos = getattr(f, "pos1", None) or ""
            canon = getattr(f, "lemma", None) or w.surface
            orth = getattr(f, "orthBase", None) or w.surface
            loan = "-" in canon
            if _has_kanji(orth) or loan or not _has_kanji(canon):
                shown = orth
            else:
                shown = canon  # kana-written word: show its usual kanji form
            reading_src = orth if loan else (getattr(f, "lForm", None) or "")
            out.append(Token(w.surface, shown, canon, _hira(reading_src), pos))
        return out


def content_words(tokens: list[Token]) -> list[Token]:
    seen, out = set(), []
    for t in tokens:
        if t.pos in SKIP_POS or not t.surface.strip():
            continue
        k = (t.key, t.reading)
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out
