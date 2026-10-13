import json

import pytest

from yomiplay.store.history import read_history


def session(root, name, events, serial=None, tagged=True):
    d = root / name
    d.mkdir(parents=True)
    lines = [{"kind": "session_start", "serial": serial}] if tagged else []
    lines += events
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    return d


def ask(q):
    return {"ts": "t", "kind": "ask", "question": q, "answer": "a-" + q}


def questions(page):
    return [e.get("question") for e in page["entries"]]


def test_current_session_first_then_older_sessions_oldest_first(tmp_path):
    session(tmp_path, "20260101-100000", [ask("a1"), ask("a2")], serial="X")
    session(tmp_path, "20260102-100000", [ask("b1")], serial="X")
    cur = session(tmp_path, "20260103-100000", [ask("c1")], serial="X")
    page = read_history(tmp_path, cur, "X", 50)
    assert questions(page) == ["a1", "a2", "b1", "c1"]
    assert [e["session"] for e in page["entries"]] == ["20260101-100000"] * 2 + ["20260102-100000", "20260103-100000"]
    assert page["session"] == "20260103-100000"
    assert page["before"] is None


def test_cursor_pages_back_without_gaps_or_repeats(tmp_path):
    session(tmp_path, "20260101-100000", [ask(f"a{i}") for i in range(5)], serial="X")
    cur = session(tmp_path, "20260102-100000", [ask("c0"), ask("c1"), ask("c2")], serial="X")
    seen, before = [], None
    for _ in range(10):
        page = read_history(tmp_path, cur, "X", 2, before)
        seen = questions(page) + seen
        before = page["before"]
        if before is None:
            break
    assert seen == ["a0", "a1", "a2", "a3", "a4", "c0", "c1", "c2"]


def test_other_games_are_skipped_and_untagged_sessions_kept(tmp_path):
    session(tmp_path, "20260101-100000", [ask("old")], tagged=False)
    session(tmp_path, "20260102-100000", [ask("other")], serial="Y")
    cur = session(tmp_path, "20260103-100000", [ask("mine")], serial="X")
    assert questions(read_history(tmp_path, cur, "X", 50)) == ["old", "mine"]


def test_unknown_serial_only_matches_unknown_or_untagged(tmp_path):
    session(tmp_path, "20260101-100000", [ask("x")], serial="X")
    session(tmp_path, "20260102-100000", [ask("none")], serial=None)
    cur = session(tmp_path, "20260103-100000", [ask("cur")], serial=None)
    assert questions(read_history(tmp_path, cur, None, 50)) == ["none", "cur"]


def test_bad_lines_other_dirs_and_corrections(tmp_path):
    d = session(tmp_path, "20260101-100000", [
        {"kind": "explain", "card_id": "k", "card": {"lines": [{"source": "old"}], "words": []}},
        {"kind": "correct_line", "card_id": "k", "line_index": 0, "text": "new"},
        {"kind": "agent_step"}], serial="X")
    with (d / "events.jsonl").open("a") as f:
        f.write('{"kind": "ask", "quest')  # half-written last line
    (tmp_path / "not-a-session").mkdir()
    (tmp_path / "20260102-100000").mkdir()  # no events file
    cur = session(tmp_path, "20260103-100000", [], serial="X")
    page = read_history(tmp_path, cur, "X", 50)
    assert [e["kind"] for e in page["entries"]] == ["explain"]
    assert page["entries"][0]["card"]["lines"][0]["source"] == "new"


@pytest.mark.parametrize("before", ["nope", "20260101-100000", "20260101-100000:x", "../x:1", "20269999-999999:1"])
def test_bad_cursor_is_rejected(tmp_path, before):
    cur = session(tmp_path, "20260101-100000", [ask("a")], serial="X")
    with pytest.raises(ValueError):
        read_history(tmp_path, cur, "X", 50, before)


def test_tag_must_be_the_first_line_and_other_events_are_ignored(tmp_path):
    d = session(tmp_path, "20260101-100000", [{"kind": "agent_step", "question": "no"}, ask("a")], tagged=False)
    with (d / "events.jsonl").open("a") as f:
        f.write(json.dumps({"kind": "session_start", "serial": "Y"}) + "\n")  # not first: does not tag
    cur = session(tmp_path, "20260102-100000", [], serial="X")
    assert questions(read_history(tmp_path, cur, "X", 50)) == ["a"]
