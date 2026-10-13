"""The study card the model fills in. Languages are keys, so any target languages work."""
from __future__ import annotations

from pydantic import BaseModel, Field


class StudyLine(BaseModel):
    source: str
    reading: str = ""
    romaji: str = ""
    translations: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    box: list[float] | None = None


class StudyWord(BaseModel):
    word: str
    reading: str = ""
    romaji: str = ""
    meanings: dict[str, str] = Field(default_factory=dict)
    part_of_speech: str = ""


class StudyCard(BaseModel):
    lines: list[StudyLine] = Field(default_factory=list)
    words: list[StudyWord] = Field(default_factory=list)
    summary: str = ""


def card_schema(target_languages: list[str], source_language: str = "ja") -> dict:
    langs = {"type": "object", "properties": {l: {"type": "string"} for l in target_languages},
             "required": list(target_languages)}
    romaji = ["romaji"] if source_language == "ja" else []  # only Japanese needs a Latin-letter pronunciation
    return {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": {"type": "object", "properties": {
                "source": {"type": "string"}, "reading": {"type": "string"}, "romaji": {"type": "string"},
                "translations": langs, "note": {"type": "string"},
                "box": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4,
                        "description": "[x, y, width, height] of this line on the image, 0-1000 scale"}},
                "required": ["source", "reading", *romaji, "translations"]}},
            "words": {"type": "array", "items": {"type": "object", "properties": {
                "word": {"type": "string"}, "reading": {"type": "string"}, "romaji": {"type": "string"},
                "meanings": langs, "part_of_speech": {"type": "string"}},
                "required": ["word", "reading", *romaji, "meanings"]}},
            "summary": {"type": "string"},
        },
        "required": ["lines", "words"],
    }
