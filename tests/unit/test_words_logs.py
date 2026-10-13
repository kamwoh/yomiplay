import json
import time
from concurrent.futures import ThreadPoolExecutor

from yomiplay.store.logs import EventLog
from yomiplay.store.words import Encounter, WordInput, WordStore


def enc(card="c1", line=0, session="s1", text="あしたは みずうみで あそぶ"):
    return Encounter(card, line, text, session, 100, "shot-100.png", "ja-study", "abc", "{}")


W_LAKE = WordInput("ja", "湖", "湖", "みずうみ", "名詞", {"en": "lake"})
W_PLAY = WordInput("ja", "遊ぶ", "遊ぶ", "あそぶ", "動詞", {})


def test_record_counts_and_merges_meanings(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    ids = ws.record([W_LAKE, W_PLAY], enc())
    ws.record([WordInput("ja", "湖", "湖", "みずうみ", "名詞", {"zh": "湖"})], enc(card="c2"))
    rows = {r.lemma: r for r in ws.list()}
    assert rows["湖"].seen_count == 2 and rows["湖"].meanings == {"en": "lake", "zh": "湖"}
    assert rows["遊ぶ"].seen_count == 1 and len(ids) == 2
    assert next(r.lemma for r in ws.list(sort="count")) == "湖"


def test_star_and_filters(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    lake, _play = ws.record([W_LAKE, W_PLAY], enc(session="s1"))
    ws.record([WordInput("ja", "本", "本", "ほん", "名詞", {})], enc(session="s2"))
    ws.star(lake, True)
    assert [r.lemma for r in ws.list(filter="starred")] == ["湖"]
    assert [r.lemma for r in ws.list(filter="session", session="s2")] == ["本"]


def test_clear_line_removes_encounters_and_unstarred_orphans(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    lake, _play = ws.record([W_LAKE, W_PLAY], enc())
    ws.star(lake, True)
    ws.clear_line("c1", 0)
    rows = {r.lemma: r for r in ws.list()}
    assert "遊ぶ" not in rows               # unstarred, no encounters left
    assert rows["湖"].seen_count == 0       # starred words are kept
    assert ws.encounters(lake) == []


def test_encounters_listed(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    (lake, _) = ws.record([W_LAKE, W_PLAY], enc())
    e = ws.encounters(lake)
    assert e[0].screenshot == "shot-100.png" and e[0].frame_index == 100


def test_event_log(tmp_path):
    log = EventLog(tmp_path)
    log.append("ask", question="hi", latency_s=1.5)
    name = log.save_png(b"\x89PNG fake", 42)
    line = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
    assert line["kind"] == "ask" and "ts" in line and name == "shot-42.png"
    assert (tmp_path / "shots" / name).read_bytes() == b"\x89PNG fake"


def test_concurrent_record_thread_safety(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    lake_word = WordInput("ja", "湖", "湖", "みずうみ", "名詞", {"en": "lake"})

    def record_word(card_num: int) -> None:
        for i in range(25):
            ws.record([lake_word], enc(card=f"c{card_num}-{i}"))

    with ThreadPoolExecutor(max_workers=8) as executor:
        executor.map(record_word, range(8))

    rows = ws.list()
    assert len(rows) == 1
    assert rows[0].seen_count == 200
    encounters = ws.encounters(rows[0].id)
    assert len(encounters) == 200


def test_star_unstar(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    lake, _play = ws.record([W_LAKE, W_PLAY], enc())
    ws.star(lake, True)
    assert [r.lemma for r in ws.list(filter="starred")] == ["湖"]
    ws.star(lake, False)
    assert ws.list(filter="starred") == []


def test_list_sort_recent(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    ws.record([W_LAKE], enc(card="c1"))
    time.sleep(1.1)
    ws.record([W_PLAY], enc(card="c2"))
    time.sleep(1.1)
    ws.record([W_LAKE], enc(card="c3"))
    rows = ws.list(sort="recent")
    assert rows[0].lemma == "湖"


def test_list_limit_honoured(tmp_path):
    ws = WordStore(tmp_path / "w.sqlite")
    for i in range(10):
        ws.record([WordInput("ja", f"word{i}", f"word{i}", f"reading{i}", "名詞", {})], enc(card=f"c{i}"))
    rows = ws.list(limit=5)
    assert len(rows) == 5
