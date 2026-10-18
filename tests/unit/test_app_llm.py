import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yomiplay.config import Config, LLMConfig, ServerConfig
from yomiplay.core.fake import FakeEmulator
from yomiplay.llm.claude_cli import ClaudeCLIBackend
from yomiplay.server.app import create_app
from yomiplay.store import llm_choice


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    d.mkdir()
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(d))
    return d


def client(tmp_path, cfg=None):
    cfg = cfg or Config(server=ServerConfig(host="testserver"))
    # no backend passed: the app builds real ClaudeCLIBackend objects (nothing is spawned in these tests)
    return TestClient(create_app(cfg, Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path / "data"))


def test_defaults_come_from_config(tmp_path, cfg_dir):
    cfg = Config(server=ServerConfig(host="testserver"), llm=LLMConfig(model="sonnet", thinking="high"))
    with client(tmp_path, cfg) as c:
        body = c.get("/api/llm").json()
        assert body["chat"] == {"model": "sonnet", "thinking": "high"}
        assert None in body["models"] and "off" in body["thinking"]


def test_put_changes_the_backend_and_persists(tmp_path, cfg_dir):
    with client(tmp_path) as c:
        r = c.put("/api/llm", json={"target": "chat", "model": "sonnet", "thinking": "off"})
        assert r.status_code == 200 and r.json()["chat"] == {"model": "sonnet", "thinking": "off"}
        backend = c.app.state.rt.llm_backends["chat"]
        assert isinstance(backend, ClaudeCLIBackend) and (backend.model, backend.thinking) == ("sonnet", "off")
    saved = json.loads((cfg_dir / "llm.json").read_text())
    assert saved == {"chat": {"model": "sonnet", "thinking": "off"}}
    with client(tmp_path) as c:  # a restart keeps the choice
        assert c.get("/api/llm").json()["chat"] == {"model": "sonnet", "thinking": "off"}


def test_a_full_model_id_from_config_does_not_block_other_changes(tmp_path, cfg_dir):
    cfg = Config(server=ServerConfig(host="testserver"), llm=LLMConfig(model="claude-sonnet-5-5"))
    with client(tmp_path, cfg) as c:
        r = c.put("/api/llm", json={"target": "chat", "model": "claude-sonnet-5-5", "thinking": "high"})
        assert r.status_code == 200 and r.json()["chat"] == {"model": "claude-sonnet-5-5", "thinking": "high"}


def test_config_rejects_unknown_thinking():
    with pytest.raises(ValueError):
        LLMConfig(thinking="on")


@pytest.mark.parametrize("body", [{"target": "x", "model": None}, {"target": "chat", "model": "gpt"},
                                  {"target": "chat", "model": "claude-$(rm)"},
                                  {"target": "agent", "model": "opus"}, {"target": "chat", "thinking": "lots"}])
def test_put_rejects_bad_choices(tmp_path, cfg_dir, body):
    with client(tmp_path) as c:
        assert c.put("/api/llm", json=body).status_code == 400
    assert not (cfg_dir / "llm.json").exists()


def test_put_is_behind_the_origin_guard(tmp_path, cfg_dir):
    with client(tmp_path) as c:
        r = c.put("/api/llm", json={"target": "chat", "model": "opus"}, headers={"origin": "http://evil.example"})
        assert r.status_code == 403


def test_load_ignores_invalid_entries(tmp_path):
    p = tmp_path / "llm.json"
    defaults = {"chat": {"model": None, "thinking": None}}
    p.write_text(json.dumps({"chat": {"model": "gpt"}}))
    assert llm_choice.load(p, defaults) == defaults
    p.write_text(json.dumps({"chat": {"model": "opus", "thinking": "max"}}))
    assert llm_choice.load(p, defaults) == {"chat": {"model": "opus", "thinking": "max"}}
    p.write_text("not json")
    assert llm_choice.load(p, defaults) == defaults
