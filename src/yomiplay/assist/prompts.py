"""Prompt text. Fixed base instructions + profile fields + per-game hints."""
from __future__ import annotations

from yomiplay.assist.profiles import ExplainProfile
from yomiplay.games.profile import GameProfile

PROMPT_VERSION = "2"

LANG_NAMES = {"en": "English", "zh": "Simplified Chinese", "zh-Hant": "Traditional Chinese", "ja": "Japanese",
              "ms": "Malay", "ko": "Korean", "fr": "French", "de": "German", "es": "Spanish"}

SYSTEM_PROMPT = (
    "You are a language companion for someone playing a video game. You receive an image of the current "
    "game screen (sometimes only the dialogue box, enlarged). Help the player understand the text they see. "
    "Never invent text that is not visible; if something is unreadable, say so."
)


def _lang(code: str) -> str:
    return LANG_NAMES.get(code, code)


def _game(game: GameProfile) -> str:
    return f"Game: {game.name}. {game.prompt_hints}".strip()


def explain_prompt(profile: ExplainProfile, game: GameProfile) -> str:
    langs = ", ".join(f"{_lang(c)} (key '{c}')" for c in profile.target_languages)
    return "\n".join([
        _game(game),
        f"Learner level: {profile.level}.",
        (
            f"First transcribe the {_lang(profile.source_language)} text on screen exactly as written, one entry per "
            "line of dialogue, keeping the original script. Then fill in each field."
        ),
        (
            "For each line, give its bounding box on the image in 'box' as [x, y, width, height] on a 0-1000 scale "
            "(0,0 is the top-left corner of the image), covering every character of that line."
        ),
        f"Translate into: {langs}.",
        "Readings use hiragana for Japanese."
        + (" Also give Hepburn romaji (Latin letters, lower case, words separated by spaces) for every line "
           "and every word in the 'romaji' field." if profile.source_language == "ja" else ""),
        profile.style.strip(),
    ]).strip()


def ask_prompt(profile: ExplainProfile, game: GameProfile, question: str) -> str:
    return "\n".join([
        _game(game),
        f"Answer in {_lang(profile.target_languages[0])}. Learner level: {profile.level}.",
        profile.style.strip(),
        f"Question: {question}",
    ]).strip()
