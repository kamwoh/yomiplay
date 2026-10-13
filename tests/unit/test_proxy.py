import os
import signal
from pathlib import Path

import pytest

from yomiplay.core.protocol import Emulator, EmulatorCrashed, EmulatorError
from yomiplay.core.proxy import EmulatorProxy, EmulatorSpec
from yomiplay.types import InputState, MemRegion


@pytest.fixture
def proxy():
    p = EmulatorProxy(EmulatorSpec(kind="fake"))
    yield p
    p.close()


def test_proxy_implements_protocol(proxy):
    assert isinstance(proxy, Emulator)


def test_round_trip(proxy):
    av = proxy.load(Path("fake.cue"))
    assert av.base_w == 320
    r = proxy.step(InputState((8, 0)), n_frames=2)
    assert r.frame.index == 2 and proxy.frame_index == 2
    assert proxy.read_memory(MemRegion.SYSTEM_RAM, 4, 2) == (8).to_bytes(2, "little")
    blob = proxy.save_state()
    proxy.step(InputState())
    proxy.load_state(blob)
    assert proxy.provenance.game_serial == "FAKE-00000"


def test_concurrent_calls_are_serialised(proxy):
    import threading
    proxy.load(Path("fake.cue"))
    errors = []

    def work():
        try:
            for _ in range(50):
                proxy.step(InputState())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and proxy.frame_index == 200


def test_errors_are_reraised(proxy):
    with pytest.raises(EmulatorError):
        proxy.step(InputState())  # not loaded


def test_crash_detected(proxy):
    proxy.load(Path("fake.cue"))
    os.kill(proxy.pid, signal.SIGKILL)
    with pytest.raises(EmulatorCrashed):
        proxy.step(InputState())


def test_close_kills_a_hung_worker():
    import time
    p = EmulatorProxy(EmulatorSpec(kind="fake"))
    p.load(Path("fake.cue"))
    os.kill(p.pid, signal.SIGSTOP)  # worker alive but never answers
    t = time.monotonic()
    p.close()
    assert time.monotonic() - t < 10
    assert not p._proc.is_alive()


def test_close_while_another_thread_holds_the_pipe():
    import threading
    import time
    p = EmulatorProxy(EmulatorSpec(kind="fake"))
    p.load(Path("fake.cue"))
    os.kill(p.pid, signal.SIGSTOP)
    caller = threading.Thread(target=lambda: pytest.raises(EmulatorCrashed, p.step, InputState()), daemon=True)
    caller.start()  # blocks inside _call holding the lock
    time.sleep(0.2)
    t = time.monotonic()
    p.close()
    assert time.monotonic() - t < 10 and not p._proc.is_alive()
    caller.join(timeout=5)
    assert not caller.is_alive()


def test_close_after_crash_reaps_the_process(proxy):
    proxy.load(Path("fake.cue"))
    os.kill(proxy.pid, signal.SIGKILL)
    with pytest.raises(EmulatorCrashed):
        proxy.step(InputState())
    proxy.close()
    assert proxy._proc.exitcode is not None
    proxy.close()  # idempotent


def test_reset_round_trip(proxy):
    proxy.load(Path("fake.cue"))
    proxy.step(InputState(), n_frames=5)
    proxy.reset()
    assert proxy.step(InputState()).frame.index == 6
    assert int.from_bytes(proxy.read_memory(MemRegion.SYSTEM_RAM, 0, 4), "little") == 1


def test_reset_before_load_is_an_emulator_error(proxy):
    with pytest.raises(EmulatorError):
        proxy.reset()
