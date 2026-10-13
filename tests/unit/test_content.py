import hashlib

from yomiplay.core.content import content_sha256, cue_tracks


def test_cue_tracks_and_hash(tmp_path):
    (tmp_path / "Game A.bin").write_bytes(b"track-one")
    (tmp_path / "Game A (Track 2).bin").write_bytes(b"track-two")
    cue = tmp_path / "Game A.cue"
    cue.write_text('FILE "Game A.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                   'FILE "Game A (Track 2).bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n')
    assert [p.name for p in cue_tracks(cue)] == ["Game A.bin", "Game A (Track 2).bin"]
    h = hashlib.sha256(cue.read_bytes() + b"track-one" + b"track-two").hexdigest()
    assert content_sha256(cue) == h


def test_plain_file_hash(tmp_path):
    f = tmp_path / "x.iso"
    f.write_bytes(b"abc")
    assert content_sha256(f) == hashlib.sha256(b"abc").hexdigest()
