import threading
import time

from yomiplay.runtime.clock import ManualClock, RealtimeClock
from yomiplay.runtime.inputs import HumanInput, ScriptedInput
from yomiplay.types import Button, InputState


def test_human_input_latest_wins_across_threads():
    h = HumanInput()
    t = threading.Thread(target=lambda: h.set_port(0, int(Button.START)))
    t.start(); t.join()
    assert h.poll(None) == InputState((int(Button.START), 0))
    h.set_port(1, 3)
    assert h.poll(None).ports == (int(Button.START), 3)


def test_scripted_input_holds_state_between_events():
    s = ScriptedInput({0: InputState((1, 0)), 3: InputState((2, 0))})
    got = [s.poll(None).port(0) for _ in range(5)]
    assert got == [1, 1, 1, 2, 2]


def test_manual_clock_counts():
    c = ManualClock(); c.start(60.0)
    for _ in range(5):
        c.tick()
    assert c.ticks == 5


def test_realtime_clock_paces_close_to_fps():
    c = RealtimeClock(); c.start(200.0)
    t0 = time.perf_counter()
    for _ in range(40):
        c.tick()
    elapsed = time.perf_counter() - t0
    assert 0.17 < elapsed < 0.35  # 40 ticks at 200 Hz = 0.2 s


def test_realtime_rate_is_clamped():
    c = RealtimeClock(); c.start(60.0)
    c.set_rate(5.0)
    assert c.rate == 1.02
    c.set_rate(0.1)
    assert c.rate == 0.98
