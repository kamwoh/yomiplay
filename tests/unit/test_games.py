from yomiplay.games.profile import GameProfile, load_profile
from yomiplay.games.serial import read_serial

from .isofake import build_iso, to_mode1_raw, to_mode2_raw

CNF = b"BOOT = cdrom:\\SLPS_123.45;1\r\nTCB = 4\r\n"


def test_serial_from_iso(tmp_path):
    p = tmp_path / "g.iso"
    p.write_bytes(build_iso({b"SYSTEM.CNF;1": CNF}))
    assert read_serial(p) == "SLPS-12345"


def test_serial_from_cue_bin(tmp_path):
    (tmp_path / "g.bin").write_bytes(to_mode2_raw(build_iso({b"SYSTEM.CNF;1": CNF})))
    cue = tmp_path / "g.cue"
    cue.write_text('FILE "g.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    assert read_serial(cue) == "SLPS-12345"


def test_serial_missing_returns_none(tmp_path):
    p = tmp_path / "g.iso"
    p.write_bytes(build_iso({b"README.TXT;1": b"hello"}))
    assert read_serial(p) is None
    assert read_serial(tmp_path / "does-not-exist.cue") is None


def test_serial_from_mode1_cue(tmp_path):
    (tmp_path / "g.bin").write_bytes(to_mode1_raw(build_iso({b"SYSTEM.CNF;1": CNF})))
    cue = tmp_path / "g.cue"
    cue.write_text('FILE "g.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n')
    assert read_serial(cue) == "SLPS-12345"


def test_serial_empty_and_truncated_images_return_none(tmp_path):
    empty = tmp_path / "e.iso"
    empty.write_bytes(b"\0" * 100)
    assert read_serial(empty) is None
    full = build_iso({b"SYSTEM.CNF;1": CNF})
    cut_pvd = tmp_path / "t.iso"
    cut_pvd.write_bytes(full[: 17 * 2048])  # ends right after the PVD
    assert read_serial(cut_pvd) is None
    cut_file = tmp_path / "f.iso"
    cut_file.write_bytes(full[: 19 * 2048])  # root present, SYSTEM.CNF sector missing
    assert read_serial(cut_file) is None


def test_serial_malformed_cue_returns_none(tmp_path):
    cue = tmp_path / "g.cue"
    cue.write_text("garbage\n")
    assert read_serial(cue) is None


def test_profile_lookup_and_default(tmp_path):
    (tmp_path / "_default.toml").write_text('name = "Unknown game"\n')
    (tmp_path / "SLPS-12345.toml").write_text(
        'name = "Test Game"\ndialogue_rects = [[0.05, 0.62, 0.9, 0.3]]\nprompt_hints = "An invented hint."\n')
    p = load_profile("SLPS-12345", [tmp_path])
    assert isinstance(p, GameProfile) and p.dialogue_rects == [(0.05, 0.62, 0.9, 0.3)]
    assert load_profile("SLPS-99999", [tmp_path]).name == "Unknown game"
    assert load_profile(None, [tmp_path / "nowhere"]).name == "Unknown game"


def test_earlier_dir_wins(tmp_path):
    user, repo = tmp_path / "user", tmp_path / "repo"
    user.mkdir(); repo.mkdir()
    (user / "SLPS-12345.toml").write_text('name = "Measured by me"\n')
    (repo / "SLPS-12345.toml").write_text('name = "Shipped"\n')
    assert load_profile("SLPS-12345", [user, repo]).name == "Measured by me"


def test_malformed_profile_names_the_file(tmp_path):
    import pytest

    from yomiplay.games.profile import GameProfileError
    (tmp_path / "SLPS-12345.toml").write_text("name = ")
    with pytest.raises(GameProfileError, match="SLPS-12345.toml"):
        load_profile("SLPS-12345", [tmp_path])
    (tmp_path / "SLPS-12345.toml").write_text("dialogue_rects = 3\n")  # valid TOML, invalid profile
    with pytest.raises(GameProfileError, match="SLPS-12345.toml"):
        load_profile("SLPS-12345", [tmp_path])
