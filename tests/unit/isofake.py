"""Build tiny synthetic ISO9660 images for tests (invented content only)."""
import struct


def _dir_record(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    rec = struct.pack("<BBI", 0, 0, lba) + struct.pack(">I", lba) + struct.pack("<I", size) + struct.pack(">I", size)
    rec += b"\0" * 7 + bytes([2 if is_dir else 0, 0, 0]) + struct.pack("<H", 1) + struct.pack(">H", 1)
    rec += bytes([len(name)]) + name
    if len(rec) % 2:
        rec += b"\0"
    return bytes([len(rec)]) + rec[1:]


def build_iso(files: dict[bytes, bytes]) -> bytes:
    """files: {b'SYSTEM.CNF;1': data}. Returns 2048-byte-sector image."""
    sectors = [b"\0" * 2048] * 16
    root_lba = 18
    next_lba = 19
    records = [_dir_record(b"\0", root_lba, 2048, True), _dir_record(b"\1", root_lba, 2048, True)]
    blobs = []
    for name, data in files.items():
        records.append(_dir_record(name, next_lba, len(data), False))
        blobs.append(data.ljust(2048, b"\0"))
        next_lba += 1
    root = b"".join(records).ljust(2048, b"\0")
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[156:156 + 34] = _dir_record(b"\0", root_lba, 2048, True)
    sectors.append(bytes(pvd))
    sectors.append(b"\xff" + b"CD001" + b"\0" * 2042)  # terminator
    sectors.append(root)
    sectors.extend(blobs)
    return b"".join(sectors)


def to_mode2_raw(iso: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(iso), 2048):
        out += b"\0" + b"\xff" * 10 + b"\0" + b"\0\0\0\x02" + b"\0" * 8 + iso[i:i + 2048] + b"\0" * 280
    return bytes(out)


def to_mode1_raw(iso: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(iso), 2048):
        out += b"\0" + b"\xff" * 10 + b"\0" + b"\0\0\0\x01" + iso[i:i + 2048] + b"\0" * 288
    return bytes(out)
