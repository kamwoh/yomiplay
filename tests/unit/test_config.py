from pathlib import Path

from yomiplay.config import Config, load_config
from yomiplay.store.paths import DataPaths, config_root, data_root


def test_env_overrides_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("YOMIPLAY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(tmp_path / "cfg"))
    assert data_root() == tmp_path / "data"
    assert config_root() == tmp_path / "cfg"


def test_data_paths_layout(tmp_path):
    p = DataPaths(tmp_path)
    assert p.words_db == tmp_path / "words.sqlite"
    assert p.states_dir("SLPS-00000") == tmp_path / "states" / "SLPS-00000"
    assert p.memcards_dir.is_dir() and p.sessions_dir.is_dir()


def test_load_config_defaults_when_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert isinstance(cfg, Config)
    assert cfg.server.port == 8765 and cfg.llm.backend == "claude_cli"
    assert cfg.keys.mapping["Enter"] == "START"


def test_load_config_reads_toml(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[core]\ncore_path = "/x/core.so"\nbios_dir = "/x/bios"\n[server]\nport = 9000\n')
    cfg = load_config(f)
    assert cfg.core.core_path == Path("/x/core.so") and cfg.server.port == 9000
