import numpy as np
import pytest

from yomiplay.store.states import SlotCorrupt, StateMismatch, StateStore
from yomiplay.types import Frame, Provenance

PROV = Provenance(core_sha256="c" * 64, content_sha256="g" * 64, game_serial="FAKE-00000")


def frame():
    rgba = np.zeros((240, 320, 4), np.uint8); rgba[..., 0] = 200; rgba[..., 3] = 255
    return Frame(42, rgba)


def test_put_get_list(tmp_path):
    s = StateStore(tmp_path)
    info = s.put(3, b"state-bytes" * 1000, frame(), PROV)
    assert info.slot == 3 and info.frame_index == 42 and info.has_thumb
    assert s.get(3, PROV) == b"state-bytes" * 1000
    assert [i.slot for i in s.list()] == [3]
    assert s.thumb_path(3).stat().st_size > 0


def test_mismatched_provenance_refused(tmp_path):
    s = StateStore(tmp_path)
    s.put(1, b"x", frame(), PROV)
    other = Provenance(core_sha256="d" * 64, content_sha256="g" * 64)
    with pytest.raises(StateMismatch):
        s.get(1, other)


def test_empty_slot_and_bad_slot(tmp_path):
    s = StateStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        s.get(2, PROV)
    with pytest.raises(ValueError):
        s.put(0, b"x", frame(), PROV)


def test_content_sha256_mismatch_raises_statemismatch(tmp_path):
    s = StateStore(tmp_path)
    s.put(1, b"x", frame(), PROV)
    other = Provenance(core_sha256="c" * 64, content_sha256="h" * 64)
    with pytest.raises(StateMismatch):
        s.get(1, other)


def test_state_without_json_raises_slotcorrupt(tmp_path):
    s = StateStore(tmp_path)
    # Manually create a .state file without a .json sidecar
    state_p = tmp_path / "slot-1.state"
    import zlib
    state_p.write_bytes(zlib.compress(b"data", 1))

    with pytest.raises(SlotCorrupt):
        s.get(1, PROV)


def test_corrupt_state_raises_slotcorrupt(tmp_path):
    s = StateStore(tmp_path)
    s.put(1, b"x", frame(), PROV)
    # Corrupt the state file by truncating it
    state_p = tmp_path / "slot-1.state"
    state_p.write_bytes(b"x")

    with pytest.raises(SlotCorrupt):
        s.get(1, PROV)


def test_list_skips_malformed_sidecar(tmp_path):
    s = StateStore(tmp_path)
    s.put(1, b"x", frame(), PROV)
    s.put(3, b"y", frame(), PROV)
    # Corrupt slot 2's sidecar
    json_p = tmp_path / "slot-2.json"
    json_p.write_text("{invalid json")

    slots = [i.slot for i in s.list()]
    assert slots == [1, 3]  # Slot 2 with malformed sidecar is skipped
