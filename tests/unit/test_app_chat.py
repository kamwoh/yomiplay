import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from yomiplay.config import Config, ServerConfig
from yomiplay.core.fake import FakeEmulator
from yomiplay.llm.fake import FakeBackend
from yomiplay.llm.protocol import Delta, Final, LLMError, Progress, Usage
from yomiplay.server.app import create_app

CARD = {"lines": [{"source": "あしたは みずうみで あそぼう", "reading": "あしたは みずうみで あそぼう",
                   "translations": {"en": "Let's play at the lake tomorrow", "zh": "明天去湖边玩吧"}, "note": ""}],
        "words": [{"word": "湖", "reading": "みずうみ", "meanings": {"en": "lake", "zh": "湖"}}], "summary": ""}



def local_cfg() -> Config:
    # TestClient talks to the app as host "testserver"; allow it the way a configured bind host is allowed
    return Config(server=ServerConfig(host="testserver"))

def client(tmp_path, replies):
    app = create_app(local_cfg(), Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path,
                     backend=FakeBackend(replies))
    return TestClient(app)


def until_done(ws):
    out = []
    while True:
        m = ws.receive_json()
        out.append(m)
        if m["type"] == "done":
            return out


def test_profiles_listed(tmp_path):
    with client(tmp_path, []) as c:
        body = c.get("/api/profiles").json()
        assert body["default"] == "ja-study"
        assert {"ja-study", "tutor-chat"} <= {p["name"] for p in body["profiles"]}


def test_explain_flow_records_words_and_pauses(tmp_path):
    with client(tmp_path, [[Final("{}", CARD), Usage("fake", 1.0, cost_usd=0.01)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "explain", "chat_id": "main", "profile": "ja-study"})
            msgs = until_done(ws)
        card = next(m for m in msgs if m["type"] == "card")
        assert card["card"]["lines"][0]["translations"]["zh"] == "明天去湖边玩吧"
        assert c.get("/api/status").json()["paused"] is True
        words = c.get("/api/words").json()
        lake = next(w for w in words if w["lemma"] == "湖")
        assert lake["seen_count"] == 1
        assert c.post(f"/api/words/{lake['id']}/star", json={"starred": True}).status_code == 200
        assert [w["lemma"] for w in c.get("/api/words?filter=starred").json()] == ["湖"]
        enc = c.get(f"/api/words/{lake['id']}/encounters").json()
        assert c.get(f"/api/shots/{enc[0]['screenshot']}").headers["content-type"] == "image/png"
        r = c.post(f"/api/cards/{card['card_id']}/lines/0", json={"text": "本を 読む"}).json()
        assert len(r["word_ids"]) == 2


def test_ask_streams_and_errors_are_reported(tmp_path):
    with client(tmp_path, [[Delta("Go "), Delta("left."), Final("Go left.", None)],
                           [LLMError("limit", "usage limit reached")]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ask", "chat_id": "main", "text": "Where now?", "profile": "ja-study",
                          "with_screen": True})
            msgs = until_done(ws)
            assert "".join(m["text"] for m in msgs if m["type"] == "delta") == "Go left."
            ws.send_json({"type": "ask", "chat_id": "main", "text": "And?", "profile": "ja-study"})
            msgs = until_done(ws)
            assert msgs[0] == {"type": "error", "kind": "limit", "message": "usage limit reached"}


def test_shot_names_are_validated(tmp_path):
    with client(tmp_path, []) as c:
        assert c.get("/api/shots/..%2Fevents.jsonl").status_code == 404
        assert c.get("/api/shots/shot-1.png").status_code == 404


def test_screenshot_endpoint(tmp_path):
    with client(tmp_path, []) as c:
        start_game(c)
        r = c.get("/api/screenshot.png")
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


class SlowConversation:
    def __init__(self):
        self.stop = asyncio.Event()

    async def send(self, msg, schema=None):
        yield Delta("thinking")
        await self.stop.wait()
        yield Final("late", None)

    async def cancel(self):
        self.stop.set()

    async def close(self):
        pass


class SlowBackend:
    name = "slow"

    async def open(self, system):
        return SlowConversation()


def slow_client(tmp_path):
    app = create_app(local_cfg(), Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path, backend=SlowBackend())
    return TestClient(app)


def test_cancel_ends_with_done_and_second_request_is_rejected(tmp_path):
    ask = {"type": "ask", "chat_id": "main", "text": "hi", "profile": "ja-study", "with_screen": False}
    with slow_client(tmp_path) as c, c.websocket_connect("/ws/chat") as ws:
        ws.send_json(ask)
        assert ws.receive_json() == {"type": "delta", "text": "thinking"}
        ws.send_json(ask)
        err = ws.receive_json()
        assert err["type"] == "error" and "still answering" in err["message"]
        ws.send_json({"type": "cancel", "chat_id": "main"})
        assert until_done(ws)[-1] == {"type": "done", "chat_id": "main"}


def test_bad_filter_is_400(tmp_path):
    with client(tmp_path, []) as c:
        assert c.get("/api/words?filter=bad").status_code == 400
        assert c.get("/api/words?sort=bad").status_code == 400


def test_malformed_ws_messages_get_error_and_socket_survives(tmp_path):
    with client(tmp_path, [[Delta("ok"), Final("ok", None)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_text("{not json")
            assert ws.receive_json() == {"type": "error", "kind": "backend", "message": "bad request"}
            ws.send_text("[1, 2]")
            assert ws.receive_json()["message"] == "bad request"
            ws.send_json({"type": "ask", "chat_id": "main", "text": "x", "profile": "ja-study"})
            assert "".join(m["text"] for m in until_done(ws) if m["type"] == "delta") == "ok"


def test_out_of_range_line_index_is_400(tmp_path):
    with client(tmp_path, [[Final("{}", CARD)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "explain", "chat_id": "main", "profile": "ja-study"})
            card = next(m for m in until_done(ws) if m["type"] == "card")
        for i in (1, -1):
            r = c.post(f"/api/cards/{card['card_id']}/lines/{i}", json={"text": "本を 読む"})
            assert r.status_code == 400
        assert c.get("/api/words").json() != [] and all(w["lemma"] != "本" for w in c.get("/api/words").json())


def test_constructor_failure_closes_emulator(tmp_path, monkeypatch):
    import pytest

    from yomiplay.server import app as app_mod

    emu = FakeEmulator()
    closed = []
    orig = emu.close
    emu.close = lambda: (closed.append(1), orig())[1]

    def boom(*a, **k):
        raise RuntimeError("tokenizer broke")

    monkeypatch.setattr(app_mod, "FugashiTokenizer", boom)
    app = create_app(Config(), Path("fake.cue"), emulator=emu, data_root=tmp_path, backend=FakeBackend([]))
    with pytest.raises(RuntimeError, match="tokenizer broke"), TestClient(app):
        pass
    assert closed


def test_unexpected_companion_error_is_reported(tmp_path):
    with client(tmp_path, [[Final("{}", CARD)]]) as c:
        rt = c.app.state.rt
        start_game(c)

        def broken_save_png(*a, **k):
            raise OSError("disk full")

        rt.companion.log.save_png = broken_save_png
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "explain", "chat_id": "main", "profile": "ja-study"})
            msgs = until_done(ws)
        err = next(m for m in msgs if m["type"] == "error")
        assert err["kind"] == "backend" and err["message"] == "OSError: disk full"


def test_bad_profile_file_is_reported_not_fatal(tmp_path, monkeypatch):
    conf = tmp_path / "conf"
    (conf / "profiles").mkdir(parents=True)
    (conf / "profiles" / "broken.toml").write_text("name = ")
    (conf / "profiles" / "nolang.toml").write_text('name = "nolang"\ntarget_languages = []\n')
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(conf))
    with client(tmp_path / "data", []) as c:
        r = c.get("/api/profiles")
        assert r.status_code == 200
        body = r.json()
        assert "ja-study" in {p["name"] for p in body["profiles"]} and "nolang" not in str(body["profiles"])
        problems = " ".join(body["problems"])
        assert "broken.toml" in problems and "nolang.toml" in problems


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def start_game(c) -> None:
    """The app starts paused until a page connects; resume it and wait for the first frame."""
    c.post("/api/resume")
    assert wait_until(lambda: c.app.state.rt.player.latest_frame() is not None)


def test_progress_events_reach_the_websocket(tmp_path):
    with client(tmp_path, [[Progress("started"), Progress("receiving", 12), Delta("x"), Final("x", None)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ask", "chat_id": "main", "text": "hi", "profile": "ja-study"})
            msgs = until_done(ws)
        assert [m for m in msgs if m["type"] == "progress"] == [
            {"type": "progress", "stage": "started", "chars": 0},
            {"type": "progress", "stage": "receiving", "chars": 12}]


def test_history_lists_this_sessions_chat_oldest_first(tmp_path):
    card = {**CARD, "lines": [{**CARD["lines"][0], "romaji": "ashita wa"}]}
    with client(tmp_path, [[Delta("Go"), Final("Go left.", None)], [Final("{}", card)]]) as c:
        start_game(c)
        assert c.get("/api/history").json()["entries"] == []
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ask", "chat_id": "main", "text": "Where?", "profile": "ja-study"})
            until_done(ws)
            ws.send_json({"type": "explain", "chat_id": "main", "profile": "ja-study"})
            until_done(ws)
        page = c.get("/api/history").json()
        h = page["entries"]
        assert page["before"] is None and h[0]["session"] == page["session"]
        assert [e["kind"] for e in h] == ["ask", "explain"]
        assert h[0]["question"] == "Where?" and h[0]["answer"] == "Go left." and h[0]["ts"]
        assert h[1]["card"]["lines"][0]["romaji"] == "ashita wa" and h[1]["shot"].endswith(".png") and h[1]["card_id"]
        page = c.get("/api/history?limit=1").json()
        assert [e["kind"] for e in page["entries"]] == ["explain"]
        assert [e["kind"] for e in c.get(f"/api/history?before={page['before']}").json()["entries"]] == ["ask"]
        assert c.get("/api/history?before=nope").status_code == 400
        c.post(f"/api/cards/{h[1]['card_id']}/lines/0", json={"text": "本を 読む"})
        assert c.get("/api/history").json()["entries"][1]["card"]["lines"][0]["source"] == "本を 読む"
        assert c.get("/api/history?limit=0").status_code == 422


def test_card_and_history_carry_screen_boxes(tmp_path):
    card = {**CARD, "lines": [{**CARD["lines"][0], "box": [100, 500, 250, 100]}]}
    with client(tmp_path, [[Final("{}", card)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "explain", "chat_id": "main", "profile": "ja-study"})
            msg = next(m for m in until_done(ws) if m["type"] == "card")
        assert msg["card"]["lines"][0]["box"] == [0.1, 0.5, 0.25, 0.1]
        assert c.get("/api/history").json()["entries"][-1]["card"]["lines"][0]["box"] == [0.1, 0.5, 0.25, 0.1]


def test_history_continues_after_a_restart_and_words_filter_by_session(tmp_path):
    with client(tmp_path, [[Final("{}", CARD)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "explain", "chat_id": "main", "profile": "ja-study"})
            until_done(ws)
        first = c.get("/api/history").json()["session"]
    time.sleep(1.05)  # session folders are named by the second
    with client(tmp_path, [[Delta("Hi"), Final("Hi.", None)]]) as c:
        start_game(c)
        with c.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "ask", "chat_id": "main", "text": "Now?", "profile": "ja-study"})
            until_done(ws)
        page = c.get("/api/history").json()
        assert page["session"] != first
        assert [(e["kind"], e["session"]) for e in page["entries"]] == [("explain", first), ("ask", page["session"])]
        assert c.get("/api/words?filter=session").json() == []
        assert "湖" in [w["lemma"] for w in c.get(f"/api/words?filter=session&session={first}").json()]
        assert c.get("/api/words?filter=session&session=../x").status_code == 400
