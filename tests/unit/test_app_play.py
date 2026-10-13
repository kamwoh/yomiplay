import time
from pathlib import Path

from fastapi.testclient import TestClient

from yomiplay.config import Config, ServerConfig
from yomiplay.core.fake import FakeEmulator
from yomiplay.server.app import create_app
from yomiplay.server.media import decode_header


def local_cfg() -> Config:
    # TestClient talks to the app as host "testserver"; allow it the way a configured bind host is allowed
    return Config(server=ServerConfig(host="testserver"))

def client(tmp_path):
    app = create_app(local_cfg(), Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path)
    return TestClient(app)



def recv_bytes(ws) -> bytes:
    """Next binary media message (skips JSON status messages such as the resume notice)."""
    while True:
        m = ws.receive()
        if m.get("bytes") is not None:
            return m["bytes"]


def start_game(c) -> None:
    """The app starts paused until a page connects; resume it and wait for the first frame."""
    c.post("/api/resume")
    assert wait_for(lambda: c.app.state.rt.player.latest_frame() is not None)

def test_status_and_pause(tmp_path):
    with client(tmp_path) as c:
        s = c.get("/api/status").json()
        assert s["game"] == "Unknown game" and s["paused"] is True and s["keys"]["Enter"] == "START"
        assert c.post("/api/resume").json()["paused"] is False
        assert c.get("/api/status").json()["paused"] is False
        assert c.post("/api/pause").json()["paused"] is True


def test_media_socket_streams_video_and_audio(tmp_path):
    with client(tmp_path) as c, c.websocket_connect("/ws/media") as ws:
        kinds = set()
        for _ in range(6):
            kinds.add(decode_header(recv_bytes(ws))[0])
        assert kinds == {"VID1", "AUD1"}
        ws.send_json({"type": "audio_fill", "ms": 20})


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_input_socket_sets_and_releases_buttons(tmp_path):
    with client(tmp_path) as c:
        human = c.app.state.rt.human
        with c.websocket_connect("/ws/input") as ws:
            ws.send_text("not json")
            ws.send_json({"type": "buttons", "port": "x", "mask": 1})  # ignored, socket survives
            ws.send_json({"type": "buttons", "port": 0, "mask": 8})
            assert wait_for(lambda: human.poll(None).port(0) == 8)
        assert wait_for(lambda: human.poll(None).port(0) == 0)  # released on disconnect


def test_save_and_load_slot(tmp_path):
    with client(tmp_path) as c:
        start_game(c)
        r = c.post("/api/states/2").json()
        assert r["slot"] == 2
        assert c.get("/api/states").json()[0]["slot"] == 2
        assert c.get("/api/states/2/thumb.png").headers["content-type"] == "image/png"
        assert c.post("/api/states/2/load").json()["ok"] is True
        assert c.post("/api/states/5/load").status_code == 404


def test_disconnect_pauses_and_reconnect_resumes(tmp_path):
    with client(tmp_path) as c:
        rt = c.app.state.rt
        with c.websocket_connect("/ws/media") as ws:
            recv_bytes(ws)
        assert wait_for(lambda: rt.paused_by_disconnect and rt.player.paused)
        with c.websocket_connect("/ws/media") as ws:
            recv_bytes(ws)
            start = rt.player.latest_frame().index
            assert wait_for(lambda: rt.player.latest_frame().index > start)
        assert rt.player.latest_frame() is not None


def test_load_slot_from_other_core_is_409(tmp_path):
    with client(tmp_path) as c:
        start_game(c)
        c.post("/api/states/3")
        rt = c.app.state.rt
        (rt.states.dir / "slot-3.state").write_bytes(b"not zlib")
        r = c.post("/api/states/3/load")
        assert r.status_code == 409 and "corrupt" in r.json()["detail"]


def test_media_connect_clears_stale_audio(tmp_path):
    with client(tmp_path) as c:
        rt = c.app.state.rt
        calls = []
        orig = rt.bridge.clear_audio
        rt.bridge.clear_audio = lambda: (calls.append(1), orig())[1]
        with c.websocket_connect("/ws/media") as ws:
            recv_bytes(ws)
        assert calls == [1]


def test_user_game_profile_overrides_repo(tmp_path, monkeypatch):
    conf = tmp_path / "conf"
    (conf / "games").mkdir(parents=True)
    (conf / "games" / "_default.toml").write_text('name = "My measured profile"\n')
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(conf))
    with client(tmp_path / "data") as c:
        assert c.get("/api/status").json()["game"] == "My measured profile"


def test_malformed_game_profile_stops_startup_with_file_name(tmp_path, monkeypatch):
    import pytest

    from yomiplay.games.profile import GameProfileError
    conf = tmp_path / "conf"
    (conf / "games").mkdir(parents=True)
    (conf / "games" / "_default.toml").write_text("name = ")
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(conf))
    emu, closed = FakeEmulator(), []
    emu.close = lambda: closed.append(1)
    app = create_app(local_cfg(), Path("fake.cue"), emulator=emu, data_root=tmp_path / "data")
    with pytest.raises(GameProfileError, match="_default.toml"), TestClient(app):
        pass
    assert closed == [1]  # the emulator (a worker process in real use) is not leaked


def test_starts_paused_until_a_media_client_connects(tmp_path):
    with client(tmp_path) as c:
        rt = c.app.state.rt
        time.sleep(0.1)
        assert c.get("/api/status").json()["paused"] is True and rt.player.latest_frame() is None
        with c.websocket_connect("/ws/media") as ws:
            assert decode_header(recv_bytes(ws))[0] in ("VID1", "AUD1")
            assert c.get("/api/status").json()["paused"] is False


class CrashingEmulator(FakeEmulator):
    def step(self, inp, n_frames=1, render=True):
        if self.frame_index >= 3:
            from yomiplay.core.protocol import EmulatorCrashed
            raise EmulatorCrashed("emulator process exited (code -9)")
        return super().step(inp, n_frames, render)


def test_emulator_failure_is_kept_and_told_to_new_clients(tmp_path):
    app = create_app(local_cfg(), Path("fake.cue"), emulator=CrashingEmulator(), data_root=tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/status").json()["emulator_failed"] is None
        c.post("/api/resume")
        assert wait_for(lambda: c.get("/api/status").json()["emulator_failed"] is not None)
        assert "code -9" in c.get("/api/status").json()["emulator_failed"]
        with c.websocket_connect("/ws/media") as ws:  # a page opened after the crash still learns of it
            assert ws.receive_json() == {"type": "emulator_failed", "message": "emulator process exited (code -9)"}


def test_reset_runs_on_the_player_and_is_logged(tmp_path):
    with client(tmp_path) as c:
        start_game(c)
        assert c.post("/api/reset").json() == {"ok": True}
        events = (c.app.state.rt.session_dir / "events.jsonl").read_text()
        assert '"kind": "reset"' in events
        # the game keeps running after the reset
        n = c.app.state.rt.player.latest_frame().index
        assert wait_for(lambda: c.app.state.rt.player.latest_frame().index > n)


def test_reset_while_paused_still_works(tmp_path):
    with client(tmp_path) as c:  # starts paused until a page connects
        assert c.post("/api/reset").status_code == 200


def test_quit_requests_shutdown_after_responding(tmp_path):
    asked = []
    app = create_app(local_cfg(), Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path,
                     extra={"request_shutdown": lambda: asked.append(1)})
    with TestClient(app) as c:
        assert c.post("/api/quit").json() == {"ok": True}
        assert asked == [1]
