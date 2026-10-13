import numpy as np

from yomiplay.types import AVInfo, Button, Frame, InputState, MemRegion, Provenance, StepResult


def test_button_bits_match_libretro_joypad_ids():
    assert Button.B == 1 << 0 and Button.CROSS == Button.B
    assert Button.START == 1 << 3
    assert Button.A == 1 << 8 and Button.CIRCLE == Button.A
    assert Button.R3 == 1 << 15


def test_input_state_defaults_and_port_access():
    s = InputState()
    assert s.ports == (0, 0)
    s2 = InputState((int(Button.START | Button.CROSS), 0))
    assert s2.port(0) & Button.START
    assert s2.port(5) == 0


def test_provenance_round_trip():
    p = Provenance(core_sha256="a" * 64, content_sha256="b" * 64,
                   core_options={"beetle_psx_renderer": "software"}, game_serial="SLPS-00000", libretro_api=1)
    assert Provenance.from_dict(p.to_dict()) == p


def test_frame_and_step_result_hold_arrays():
    f = Frame(index=3, rgba=np.zeros((240, 320, 4), np.uint8))
    r = StepResult(frame=f, audio=np.zeros(1470, np.int16))
    assert r.frame.index == 3 and r.frame.width == 320 and r.frame.height == 240
    assert MemRegion.SYSTEM_RAM == 2
    assert AVInfo(59.94, 44100.0, 320, 240).fps == 59.94
