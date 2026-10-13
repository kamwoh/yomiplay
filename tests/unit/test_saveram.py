import ctypes as C

from yomiplay.core.saveram import SaveRamFile


def buf(data: bytes):
    b = (C.c_uint8 * len(data)).from_buffer_copy(data)
    return b, C.addressof(b)


def test_restore_missing_file_leaves_memory(tmp_path):
    b, ptr = buf(b"\x00" * 16)
    f = SaveRamFile(tmp_path / "card.srm")
    assert f.restore(ptr, 16) is False
    assert bytes(b) == b"\x00" * 16
    assert f.flush(ptr, 16) is False  # unchanged since restore: nothing written
    assert not (tmp_path / "card.srm").exists()


def test_flush_writes_only_on_change_and_restore_reads_back(tmp_path):
    b, ptr = buf(b"\x00" * 16)
    f = SaveRamFile(tmp_path / "card.srm")
    f.restore(ptr, 16)
    b[3] = 0x5A
    assert f.flush(ptr, 16) is True
    assert (tmp_path / "card.srm").read_bytes()[3] == 0x5A
    assert f.flush(ptr, 16) is False  # no change since last flush
    assert not list(tmp_path.glob("*.tmp"))

    b2, ptr2 = buf(b"\x00" * 16)
    assert SaveRamFile(tmp_path / "card.srm").restore(ptr2, 16) is True
    assert bytes(b2)[3] == 0x5A


def test_restore_size_mismatch_copies_overlap(tmp_path):
    (tmp_path / "card.srm").write_bytes(b"\x01" * 32)
    b, ptr = buf(b"\x00" * 16)
    assert SaveRamFile(tmp_path / "card.srm").restore(ptr, 16) is True
    assert bytes(b) == b"\x01" * 16
