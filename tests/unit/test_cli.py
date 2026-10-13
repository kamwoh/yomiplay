from yomiplay.cli import main


def test_config_before_and_after_subcommand(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("")
    assert isinstance(main(["doctor", "--config", str(cfg)]), int)
    assert isinstance(main(["--config", str(cfg), "doctor"]), int)


def test_serve_without_core_or_bios_explains_and_exits_2(tmp_path, capsys, monkeypatch):
    import pytest
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("server started without a usable core"))
    game = tmp_path / "game.cue"
    game.write_text("")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[core]\ncore_path = "{tmp_path / "missing.so"}"\nbios_dir = "{tmp_path}"\n')
    assert main(["serve", str(game), "--config", str(cfg)]) == 2
    out = capsys.readouterr().out
    assert "FIX  core:" in out and "FIX  BIOS" in out
