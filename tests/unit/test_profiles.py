from pathlib import Path

import pytest

from yomiplay.assist.profiles import ProfileLibrary
from yomiplay.assist.prompts import SYSTEM_PROMPT, ask_prompt, explain_prompt
from yomiplay.assist.schemas import StudyCard, card_schema
from yomiplay.games.profile import GameProfile

REPO_PROFILES = Path(__file__).parents[2] / "profiles"
GAME = GameProfile(name="Test Game", prompt_hints="An invented hint about the test game.")


def test_defaults_load():
    lib = ProfileLibrary([REPO_PROFILES])
    names = [p.name for p in lib.list()]
    assert names == sorted(names) and {"ja-study", "quick-translate", "tutor-chat"} <= set(names)
    assert lib.get("ja-study").target_languages == ["en", "zh"]


def test_user_override_and_missing(tmp_path):
    (tmp_path / "ja-study.toml").write_text('name = "ja-study"\ntitle = "Mine"\ntarget_languages = ["ms"]\n')
    lib = ProfileLibrary([REPO_PROFILES, tmp_path])
    assert lib.get("ja-study").target_languages == ["ms"]
    with pytest.raises(KeyError):
        lib.get("nope")


def test_ref_changes_when_profile_changes(tmp_path):
    lib = ProfileLibrary([REPO_PROFILES])
    a = lib.ref(lib.get("ja-study"))
    (tmp_path / "ja-study.toml").write_text('name = "ja-study"\ntitle = "x"\nlevel = "JLPT N3"\n')
    b = ProfileLibrary([REPO_PROFILES, tmp_path]).ref(ProfileLibrary([REPO_PROFILES, tmp_path]).get("ja-study"))
    assert a.name == b.name == "ja-study" and a.sha256 != b.sha256


def test_schema_requires_each_language():
    s = card_schema(["en", "zh"])
    tr = s["properties"]["lines"]["items"]["properties"]["translations"]
    assert tr["required"] == ["en", "zh"]
    card = StudyCard.model_validate({"lines": [{"source": "テスト", "reading": "てすと",
                                                "translations": {"en": "test", "zh": "测试"}}], "words": []})
    assert card.lines[0].translations["zh"] == "测试"


def test_prompts_include_profile_and_game_hints():
    lib = ProfileLibrary([REPO_PROFILES])
    p = explain_prompt(lib.get("ja-study"), GAME)
    assert "English" in p and "Chinese" in p and "beginner" in p and "invented hint" in p
    assert "exactly" in p  # transcribe-first instruction
    q = ask_prompt(lib.get("tutor-chat"), GAME, "What should I do next?")
    assert "What should I do next?" in q
    assert "screen" in SYSTEM_PROMPT


def test_invalid_files_are_skipped_and_reported(tmp_path):
    (tmp_path / "bad.toml").write_text("name = [")
    (tmp_path / "empty-langs.toml").write_text('name = "x"\ntarget_languages = []\n')
    lib = ProfileLibrary([REPO_PROFILES, tmp_path])
    assert "ja-study" in {p.name for p in lib.list()} and "x" not in {p.name for p in lib.list()}
    probs = lib.problems()
    assert len(probs) == 2 and any("bad.toml" in p for p in probs) and any("empty-langs.toml" in p for p in probs)


def test_schema_romaji_required_for_japanese_only():
    ja = card_schema(["en"])
    line = ja["properties"]["lines"]["items"]
    word = ja["properties"]["words"]["items"]
    assert "romaji" in line["required"] and "romaji" in word["required"]
    assert card_schema(["en"], source_language="ja") == ja
    ko = card_schema(["en"], source_language="ko")["properties"]["lines"]["items"]
    assert "romaji" in ko["properties"] and "romaji" not in ko["required"]
    card = StudyCard.model_validate({"lines": [{"source": "x", "romaji": "ekkusu"}],
                                     "words": [{"word": "x", "romaji": "ekkusu"}]})
    assert card.lines[0].romaji == "ekkusu" and card.words[0].romaji == "ekkusu"
    assert StudyCard.model_validate({"lines": [{"source": "x"}]}).lines[0].romaji == ""
