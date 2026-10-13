from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yomiplay.config import Config, ServerConfig
from yomiplay.core.fake import FakeEmulator
from yomiplay.server.app import create_app
from yomiplay.store.controls import DEFAULT_PAD


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(d))
    return d


def client(tmp_path, extra=None):
    cfg = Config(server=ServerConfig(host="testserver"))
    return TestClient(create_app(cfg, Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path / "data",
                                 extra=extra))


def test_defaults_come_from_config_and_standard_pad(tmp_path, cfg_dir):
    with client(tmp_path) as c:
        body = c.get("/api/controls").json()
        assert body["keys"]["Enter"] == "START" and body["pad"] == {str(i): b for i, b in DEFAULT_PAD.items()}
        assert body["pad"]["0"] == "CROSS" and body["pad"]["15"] == "RIGHT" and len(body["buttons"]) == 16
        assert body["defaults"]["keys"]["KeyX"] == "CROSS"
        assert not (cfg_dir / "controls.json").exists()


def test_put_persists_and_overrides_config_keys(tmp_path, cfg_dir):
    new = {"keys": {"KeyJ": "CROSS", "Space": "START"}, "pad": {"0": "CIRCLE", "1": "CROSS"}}
    with client(tmp_path) as c:
        assert c.put("/api/controls", json=new).json()["keys"] == new["keys"]
        assert c.get("/api/controls").json()["pad"] == new["pad"]
        assert c.get("/api/status").json()["keys"] == new["keys"]
    assert (cfg_dir / "controls.json").exists()
    with client(tmp_path) as c2:  # survives a restart; the config.toml mapping is replaced, not merged
        got = c2.get("/api/controls").json()
        assert got["keys"] == new["keys"] and got["pad"] == new["pad"]


@pytest.mark.parametrize("body", [
    {"keys": {"KeyJ": "TURBO"}, "pad": {}},
    {"keys": {"": "CROSS"}, "pad": {}},
    {"keys": {"KeyJ": "CROSS"}, "pad": {"32": "CROSS"}},
    {"keys": {"KeyJ": "CROSS"}, "pad": {"-1": "CROSS"}},
    {"keys": {"KeyJ": "CROSS"}, "pad": {"a": "CROSS"}},
    {"keys": {"KeyJ": "CROSS"}, "pad": {"3": "NOPE"}},
    {"keys": {"KeyJ": 5}, "pad": {}},
    {"keys": [], "pad": {}},
    {"keys": {}},
])
def test_put_rejects_bad_bindings(tmp_path, cfg_dir, body):
    with client(tmp_path) as c:
        assert c.put("/api/controls", json=body).status_code in (400, 422)
        assert c.get("/api/controls").json()["keys"]["Enter"] == "START"
    assert not (cfg_dir / "controls.json").exists()


def test_corrupt_file_falls_back_to_defaults(tmp_path, cfg_dir):
    (cfg_dir / "controls.json").write_text("{not json")
    with client(tmp_path) as c:
        assert c.get("/api/controls").json()["keys"]["Enter"] == "START"


def test_controls_put_is_behind_the_origin_guard(tmp_path, cfg_dir):
    with client(tmp_path) as c:
        r = c.put("/api/controls", json={"keys": {}, "pad": {}}, headers={"origin": "http://evil.example"})
        assert r.status_code == 403
        assert c.post("/api/reset", headers={"origin": "http://evil.example"}).status_code == 403
        assert c.post("/api/quit", headers={"origin": "http://evil.example"}).status_code == 403
