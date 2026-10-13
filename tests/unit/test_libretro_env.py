import ctypes as C

from yomiplay.core import libretro as lr


def make_core(tmp_path):
    return lr.LibretroCore.__new__(lr.LibretroCore)._init_for_tests(
        system_dir=tmp_path / "bios", save_dir=tmp_path / "saves", options={"beetle_psx_cpu_freq_scale": "100%"})


def test_pixel_format_accepted(tmp_path):
    core = make_core(tmp_path)
    fmt = C.c_int(1)
    assert core.environment(lr.ENV_SET_PIXEL_FORMAT, C.addressof(fmt)) is True
    assert core.pixel_format == 1
    bad = C.c_int(7)
    assert core.environment(lr.ENV_SET_PIXEL_FORMAT, C.addressof(bad)) is False


def test_directories_returned(tmp_path):
    core = make_core(tmp_path)
    out = C.c_char_p()
    assert core.environment(lr.ENV_GET_SYSTEM_DIRECTORY, C.addressof(out))
    assert out.value.decode() == str(tmp_path / "bios")
    assert core.environment(lr.ENV_GET_SAVE_DIRECTORY, C.addressof(out))
    assert out.value.decode() == str(tmp_path / "saves")


def test_variables_defaults_and_overrides(tmp_path):
    core = make_core(tmp_path)
    vars_ = (lr.RetroVariable * 3)(
        lr.RetroVariable(b"beetle_psx_cpu_freq_scale", b"CPU scale; 100%|200%"),
        lr.RetroVariable(b"beetle_psx_skip_bios", b"Skip BIOS; enabled|disabled"),
        lr.RetroVariable(None, None))
    assert core.environment(lr.ENV_SET_VARIABLES, C.addressof(vars_))
    q = lr.RetroVariable(b"beetle_psx_skip_bios", None)
    assert core.environment(lr.ENV_GET_VARIABLE, C.addressof(q)) and q.value == b"enabled"
    q2 = lr.RetroVariable(b"beetle_psx_cpu_freq_scale", None)
    assert core.environment(lr.ENV_GET_VARIABLE, C.addressof(q2)) and q2.value == b"100%"
    assert core.option_values() == {"beetle_psx_cpu_freq_scale": "100%", "beetle_psx_skip_bios": "enabled"}


def test_hw_render_refused_and_options_version_zero(tmp_path):
    core = make_core(tmp_path)
    assert core.environment(lr.ENV_SET_HW_RENDER, 0) is False
    v = C.c_uint(9)
    assert core.environment(lr.ENV_GET_CORE_OPTIONS_VERSION, C.addressof(v)) and v.value == 0


def test_input_bitmask_and_av_enable(tmp_path):
    core = make_core(tmp_path)
    assert core.environment(lr.ENV_GET_INPUT_BITMASKS, 0) is True
    core.set_buttons((0b1001, 0))
    assert core._input_state(0, lr.DEVICE_JOYPAD, 0, lr.JOYPAD_MASK) == 0b1001
    assert core._input_state(0, lr.DEVICE_JOYPAD, 0, 3) == 1
    assert core._input_state(1, lr.DEVICE_JOYPAD, 0, 3) == 0
    flags = C.c_int(0)
    core.video_enabled = False
    assert core.environment(lr.ENV_GET_AUDIO_VIDEO_ENABLE, C.addressof(flags)) and flags.value == 2


def test_joypad_mask_bit15_is_negative_int16(tmp_path):
    core = make_core(tmp_path)
    core.set_buttons((0x8000 | 0b1,))
    assert core._input_state(0, lr.DEVICE_JOYPAD, 0, lr.JOYPAD_MASK) == 0x8001 - 0x10000
    assert core._input_state(0, lr.DEVICE_JOYPAD, 0, 15) == 1
