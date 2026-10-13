import threading
from multiprocessing import Pipe

from yomiplay.core import worker
from yomiplay.core.worker import EmulatorSpec


class Spy:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_parent_exit_closes_emulator(monkeypatch):
    spy = Spy()
    monkeypatch.setattr(worker, "build", lambda spec: spy)
    parent, child = Pipe()
    t = threading.Thread(target=worker.serve, args=(child, EmulatorSpec("fake")))
    t.start()
    parent.close()  # parent went away without "__exit__": the worker sees EOF
    t.join(timeout=5)
    assert not t.is_alive() and spy.closed == 1


def test_build_failure_is_reported_to_requests(monkeypatch):
    def broken(spec):
        raise worker.EmulatorError("libretro spec needs core_path")

    monkeypatch.setattr(worker, "build", broken)
    parent, child = Pipe()
    t = threading.Thread(target=worker.serve, args=(child, EmulatorSpec("libretro")))
    t.start()
    parent.send(("load", ("x.cue", {})))
    assert parent.poll(5), "worker died instead of answering"
    assert parent.recv() == ("err", "EmulatorError", "libretro spec needs core_path")
    parent.send(("__exit__", ()))
    assert parent.recv() == ("ok", None)
    t.join(timeout=5)
    assert not t.is_alive()


def test_proxy_reports_bad_spec_instead_of_crashing():
    import pytest

    from yomiplay.core.protocol import EmulatorError
    from yomiplay.core.proxy import EmulatorProxy
    p = EmulatorProxy(EmulatorSpec("libretro"))
    try:
        with pytest.raises(EmulatorError, match="needs core_path"):
            p.load("x.cue")
    finally:
        p.close()
