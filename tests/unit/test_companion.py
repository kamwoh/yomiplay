from pathlib import Path

import numpy as np
import pytest

from yomiplay.assist.companion import CardReady, CompanionService
from yomiplay.assist.lexicon import FugashiTokenizer
from yomiplay.assist.profiles import ProfileLibrary
from yomiplay.games.profile import GameProfile
from yomiplay.llm.fake import FakeBackend
from yomiplay.llm.protocol import Delta, Final, LLMError, Progress, Usage
from yomiplay.store.logs import EventLog
from yomiplay.store.words import WordStore
from yomiplay.types import Frame

PROFILES = Path(__file__).parents[2] / "profiles"
CARD = {"lines": [{"source": "あしたは みずうみで あそぼう", "reading": "あしたは みずうみで あそぼう",
                   "translations": {"en": "Let's play at the lake tomorrow", "zh": "明天去湖边玩吧"}, "note": ""}],
        "words": [{"word": "湖", "reading": "みずうみ", "meanings": {"en": "lake", "zh": "湖"}}], "summary": ""}


def frame():
    rgba = np.zeros((240, 320, 4), np.uint8); rgba[..., 3] = 255
    return Frame(77, rgba)


def make(tmp_path, replies, game=None):
    be = FakeBackend(replies)
    svc = CompanionService(be, ProfileLibrary([PROFILES]), FugashiTokenizer(), WordStore(tmp_path / "w.sqlite"),
                           EventLog(tmp_path / "sess"), game or GameProfile(name="Test Game",
                           dialogue_rects=[(0.0, 0.6, 1.0, 0.4)]), session="s1", provenance_json="{}")
    return svc, be


async def test_explain_records_seen_words(tmp_path):
    svc, be = make(tmp_path, [[Final("{}", CARD), Usage("fake", 1.0)]])
    events = [e async for e in svc.explain("chat", frame(), "ja-study")]
    card = next(e for e in events if isinstance(e, CardReady))
    lemmas = {r.lemma: r for r in svc.words.list()}
    assert {"明日", "湖", "遊ぶ"} <= set(lemmas)
    assert lemmas["湖"].meanings["en"] == "lake"
    msg, schema = be.sent[0]
    assert msg.images and schema["properties"]["lines"]["items"]["properties"]["translations"]["required"] == ["en", "zh"]
    assert card.shot == "shot-77.png" and (tmp_path / "sess" / "shots" / "shot-77.png").exists()


async def test_correct_line_retokenizes(tmp_path):
    svc, _ = make(tmp_path, [[Final("{}", CARD)]])
    events = [e async for e in svc.explain("chat", frame(), "ja-study")]
    card = next(e for e in events if isinstance(e, CardReady))
    svc.correct_line(card.card_id, 0, "本を 読む")  # kanji: short hiragana like ほん is ambiguous
    lemmas = {r.lemma for r in svc.words.list()}
    assert "本" in lemmas and "読む" in lemmas and "遊ぶ" not in lemmas
    svc.correct_line(card.card_id, 0, "")
    assert svc.words.list() == []


async def test_ask_streams_text_and_logs(tmp_path):
    svc, be = make(tmp_path, [[Delta("Go "), Delta("left."), Final("Go left.", None)]])
    out = [e async for e in svc.ask("chat", "Where now?", frame(), "ja-study")]
    assert "".join(e.text for e in out if isinstance(e, Delta)) == "Go left."
    assert "Where now?" in be.sent[0][0].text and be.sent[0][1] is None
    assert '"kind": "ask"' in (tmp_path / "sess" / "events.jsonl").read_text()


async def test_free_profile_explain_streams_without_card(tmp_path):
    svc, be = make(tmp_path, [[Delta("Hi"), Final("Hi", None)]])
    out = [e async for e in svc.explain("chat", frame(), "tutor-chat")]
    assert not any(isinstance(e, CardReady) for e in out) and be.sent[0][1] is None
    assert svc.words.list() == []


async def test_model_error_passes_through(tmp_path):
    svc, _ = make(tmp_path, [[LLMError("limit", "usage limit reached")]])
    out = [e async for e in svc.explain("chat", frame(), "ja-study")]
    assert out[-1].kind == "limit"


async def test_unknown_profile_is_an_error_event(tmp_path):
    svc, _ = make(tmp_path, [])
    out = [e async for e in svc.explain("chat", frame(), "missing")]
    assert out[0].kind == "backend" and "missing" in out[0].message


async def test_each_explain_uses_a_fresh_conversation(tmp_path):
    svc, be = make(tmp_path, [[Final("{}", CARD)], [Final("{}", CARD)]])
    for _ in range(2):
        [e async for e in svc.explain("chat", frame(), "ja-study")]
    assert len(be.systems) == 2 and be.closed == 1  # the first explain conversation was closed


async def test_ask_conversation_is_kept_then_replaced_after_cap(tmp_path):
    from yomiplay.assist.companion import MAX_ASK_TURNS
    svc, be = make(tmp_path, [[Final("ok", None)]] * (MAX_ASK_TURNS + 1))
    for _ in range(MAX_ASK_TURNS):
        [e async for e in svc.ask("chat", "Where now?", None, "ja-study")]
    assert len(be.systems) == 1  # history kept for follow-up questions
    [e async for e in svc.ask("chat", "Where now?", None, "ja-study")]
    assert len(be.systems) == 2 and be.closed == 1


async def test_conversation_replaced_after_backend_or_limit_error(tmp_path):
    svc, be = make(tmp_path, [[LLMError("limit", "usage limit")], [Final("ok", None)], [LLMError("backend", "died")],
                              [Final("ok", None)], [LLMError("schema", "bad")], [Final("ok", None)]])
    for _ in range(2):
        [e async for e in svc.ask("chat", "q", None, "ja-study")]
    assert len(be.systems) == 2
    for _ in range(2):
        [e async for e in svc.ask("chat", "q", None, "ja-study")]
    assert len(be.systems) == 3
    for _ in range(2):
        [e async for e in svc.ask("chat", "q", None, "ja-study")]
    assert len(be.systems) == 3  # a schema error says nothing about the conversation's health


async def test_progress_events_pass_through_explain_and_ask(tmp_path):
    prog = [Progress("started"), Progress("receiving", 40)]
    svc, _ = make(tmp_path, [[*prog, Final("{}", CARD), Usage("fake", 1.0)], [*prog, Delta("hi"), Final("hi", None)]])
    ev = [e async for e in svc.explain("c", frame(), "ja-study")]
    assert [e for e in ev if isinstance(e, Progress)] == prog
    ev = [e async for e in svc.ask("c", "what?", frame(), "ja-study")]
    assert [e for e in ev if isinstance(e, Progress)] == prog


async def test_explain_requests_romaji_schema_and_prompt(tmp_path):
    svc, be = make(tmp_path, [[Final("{}", {**CARD, "lines": [{**CARD["lines"][0], "romaji": "ashita wa"}]})]])
    ev = [e async for e in svc.explain("c", frame(), "ja-study")]
    msg, schema = be.sent[0]
    assert "romaji" in schema["properties"]["lines"]["items"]["required"]
    assert "romaji" in msg.text.lower()
    assert next(e for e in ev if isinstance(e, CardReady)).card.lines[0].romaji == "ashita wa"


async def test_explain_maps_boxes_to_screen_fractions(tmp_path):
    # the test game crops to the bottom 40 % (dialogue_rects=[(0.0, 0.6, 1.0, 0.4)])
    card = {**CARD, "lines": [{**CARD["lines"][0], "box": [100, 250, 500, 250]}]}
    svc, be = make(tmp_path, [[Final("{}", card)]])
    events = [e async for e in svc.explain("chat", frame(), "ja-study")]
    ready = next(e for e in events if isinstance(e, CardReady))
    assert ready.card.lines[0].box == pytest.approx([0.1, 0.7, 0.5, 0.1], abs=1e-3)
    _, schema = be.sent[0]
    line = schema["properties"]["lines"]["items"]
    assert "box" in line["properties"] and "box" not in line["required"]
    assert line["properties"]["box"]["minItems"] == 4 and line["properties"]["box"]["maxItems"] == 4
    assert "0-1000" in be.sent[0][0].text or "0–1000" in be.sent[0][0].text


async def test_explain_drops_malformed_boxes(tmp_path):
    lines = [{**CARD["lines"][0], "box": [1, 2, 3]}, {**CARD["lines"][0], "box": None},
             {**CARD["lines"][0], "box": ["a", 0, 1, 1]}, {**CARD["lines"][0]}]
    svc, _ = make(tmp_path, [[Final("{}", {**CARD, "lines": lines})]])
    events = [e async for e in svc.explain("chat", frame(), "ja-study")]
    ready = next(e for e in events if isinstance(e, CardReady))
    assert [ln.box for ln in ready.card.lines] == [None, None, None, None]
