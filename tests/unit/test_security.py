from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from yomiplay.config import Config
from yomiplay.core.fake import FakeEmulator
from yomiplay.server.app import create_app
from yomiplay.server.security import rejection

PORT = 8765


@pytest.mark.parametrize("host", ["localhost", "localhost:8765", "127.0.0.1:8765", "[::1]:8765"])
def test_local_hosts_allowed(host):
    assert rejection("http", "GET", {"host": host}, PORT) is None


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "localhost:9999", "127.0.0.2:8765"])
def test_other_hosts_rejected(host):  # DNS rebinding: the browser sends the attacker's host name
    assert rejection("http", "GET", {"host": host}, PORT) is not None


@pytest.mark.parametrize("origin", ["http://localhost:8765", "http://127.0.0.1:8765"])
def test_same_origin_allowed_for_writes_and_websockets(origin):
    h = {"host": "localhost:8765", "origin": origin}
    assert rejection("http", "POST", h, PORT) is None
    assert rejection("websocket", "GET", h, PORT) is None


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:9999", "null", "https://localhost:8765"])
def test_foreign_origin_rejected_for_writes_and_websockets(origin):
    h = {"host": "localhost:8765", "origin": origin}
    assert rejection("http", "POST", h, PORT) is not None
    assert rejection("websocket", "GET", h, PORT) is not None
    assert rejection("http", "GET", h, PORT) is None  # plain reads: Host check only


def test_configured_bind_host_is_allowed():
    assert rejection("http", "POST", {"host": "pc.lan:8765", "origin": "http://pc.lan:8765"}, PORT,
                     extra_hosts=("pc.lan",)) is None


def test_app_enforces_guard(tmp_path):
    app = create_app(Config(), Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path)
    with TestClient(app, base_url="http://localhost:8765") as c:
        assert c.get("/api/status").status_code == 200
        assert c.post("/api/pause", headers={"origin": "http://evil.example"}).status_code == 403
        assert c.post("/api/pause", headers={"origin": "http://localhost:8765"}).status_code == 200
        assert c.get("/api/status", headers={"host": "evil.example:8765"}).status_code == 403
        for path in ("/ws/media", "/ws/input", "/ws/chat"):
            with pytest.raises(WebSocketDisconnect), c.websocket_connect(f"ws://localhost:8765{path}", headers={"origin": "http://evil.example"}):
                pass
        with c.websocket_connect("ws://localhost:8765/ws/input", headers={"origin": "http://localhost:8765"}) as ws:
            ws.send_json({"type": "buttons", "port": 0, "mask": 0})


def test_websocket_from_foreign_host_rejected(tmp_path):
    app = create_app(Config(), Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path)
    with TestClient(app) as c, pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws/input"):  # testserver
        pass
