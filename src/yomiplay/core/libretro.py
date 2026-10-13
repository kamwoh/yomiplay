"""Minimal ctypes libretro frontend. One core per process; all calls on one thread.

Constants and struct layouts follow libretro.h (MIT licensed, libretro/RetroArch).
"""
from __future__ import annotations

import ctypes as C
import logging
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from yomiplay.core.protocol import EmulatorError
from yomiplay.types import AVInfo

log = logging.getLogger("yomiplay.core")

EXPERIMENTAL = 0x10000
ENV_GET_CAN_DUPE = 3
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_SET_PIXEL_FORMAT = 10
ENV_SET_HW_RENDER = 14
ENV_GET_VARIABLE = 15
ENV_SET_VARIABLES = 16
ENV_GET_VARIABLE_UPDATE = 17
ENV_GET_LOG_INTERFACE = 27
ENV_GET_SAVE_DIRECTORY = 31
ENV_SET_SYSTEM_AV_INFO = 32
ENV_SET_GEOMETRY = 37
ENV_GET_AUDIO_VIDEO_ENABLE = 47 | EXPERIMENTAL
ENV_GET_INPUT_BITMASKS = 51 | EXPERIMENTAL
ENV_GET_CORE_OPTIONS_VERSION = 52
DEVICE_JOYPAD = 1
JOYPAD_MASK = 256

_LOADED_IN_PROCESS = False


class RetroGameInfo(C.Structure):
    _fields_ = [("path", C.c_char_p), ("data", C.c_void_p), ("size", C.c_size_t), ("meta", C.c_char_p)]


class RetroSystemInfo(C.Structure):
    _fields_ = [("library_name", C.c_char_p), ("library_version", C.c_char_p),
                ("valid_extensions", C.c_char_p), ("need_fullpath", C.c_bool), ("block_extract", C.c_bool)]


class RetroGameGeometry(C.Structure):
    _fields_ = [("base_width", C.c_uint), ("base_height", C.c_uint), ("max_width", C.c_uint),
                ("max_height", C.c_uint), ("aspect_ratio", C.c_float)]


class RetroSystemTiming(C.Structure):
    _fields_ = [("fps", C.c_double), ("sample_rate", C.c_double)]


class RetroSystemAVInfo(C.Structure):
    _fields_ = [("geometry", RetroGameGeometry), ("timing", RetroSystemTiming)]


class RetroVariable(C.Structure):
    _fields_ = [("key", C.c_char_p), ("value", C.c_char_p)]


ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIO_BATCH_CB = C.CFUNCTYPE(C.c_size_t, C.POINTER(C.c_int16), C.c_size_t)
INPUT_POLL_CB = C.CFUNCTYPE(None)
INPUT_STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)
LOG_CB = C.CFUNCTYPE(None, C.c_int, C.c_char_p)  # variadic in C; extra args are ignored


class LibretroCore:
    def __init__(self, core_path: Path, system_dir: Path, save_dir: Path, options: Mapping[str, str]):
        global _LOADED_IN_PROCESS
        if _LOADED_IN_PROCESS:
            raise EmulatorError("only one libretro core per process; use EmulatorProxy for more")
        self._init_for_tests(system_dir, save_dir, options)
        try:
            self.lib = C.CDLL(str(core_path))
        except OSError as e:
            raise EmulatorError(f"cannot load core {core_path}: {e}") from e
        _LOADED_IN_PROCESS = True
        try:
            self._setup()
        except BaseException:
            _LOADED_IN_PROCESS = False
            raise

    def _setup(self) -> None:
        L = self.lib
        L.retro_load_game.restype = C.c_bool
        L.retro_serialize_size.restype = C.c_size_t
        L.retro_serialize.restype = C.c_bool
        L.retro_unserialize.restype = C.c_bool
        L.retro_get_memory_data.restype = C.c_void_p
        L.retro_get_memory_size.restype = C.c_size_t
        L.retro_api_version.restype = C.c_uint
        self.api_version = int(L.retro_api_version())
        # keep every callback object alive for the life of the core (GC'd callbacks segfault)
        self._cbs = [ENV_CB(self.environment), VIDEO_CB(self._video), AUDIO_CB(self._audio_one),
                     AUDIO_BATCH_CB(self._audio_batch), INPUT_POLL_CB(lambda: None),
                     INPUT_STATE_CB(self._input_state)]
        L.retro_set_environment(self._cbs[0])
        L.retro_init()
        L.retro_set_video_refresh(self._cbs[1])
        L.retro_set_audio_sample(self._cbs[2])
        L.retro_set_audio_sample_batch(self._cbs[3])
        L.retro_set_input_poll(self._cbs[4])
        L.retro_set_input_state(self._cbs[5])
        self._loaded = False

    def _init_for_tests(self, system_dir: Path, save_dir: Path, options: Mapping[str, str]):
        # ctypes buffers kept on self: the core holds on to these pointers
        self._sys = C.create_string_buffer(str(system_dir).encode())
        self._save = C.create_string_buffer(str(save_dir).encode())
        self._overrides = {k: v for k, v in options.items()}
        self._defaults: dict[str, str] = {}
        self._value_bufs: dict[str, C.Array] = {}
        self.pixel_format = 0
        self.video_enabled = True
        self.last_video: tuple[bytes, int, int, int] | None = None
        self._audio: list[np.ndarray] = []
        self._buttons: tuple[int, ...] = (0, 0)
        self._av: AVInfo | None = None
        self._log_cb_ref = LOG_CB(self._log)
        return self

    # ---- environment -------------------------------------------------------------------------------
    def environment(self, cmd: int, data: int) -> bool:
        if cmd == ENV_SET_PIXEL_FORMAT:
            fmt = C.cast(data, C.POINTER(C.c_int))[0]
            if fmt in (0, 1, 2):
                self.pixel_format = fmt
                return True
            return False
        if cmd == ENV_GET_SYSTEM_DIRECTORY:
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.addressof(self._sys)
            return True
        if cmd == ENV_GET_SAVE_DIRECTORY:
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.addressof(self._save)
            return True
        if cmd == ENV_GET_CAN_DUPE:
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        if cmd == ENV_GET_CORE_OPTIONS_VERSION:
            C.cast(data, C.POINTER(C.c_uint))[0] = 0  # legacy SET_VARIABLES path
            return True
        if cmd == ENV_SET_VARIABLES:
            arr = C.cast(data, C.POINTER(RetroVariable))
            i = 0
            while arr[i].key:
                key = arr[i].key.decode()
                desc = (arr[i].value or b"").decode(errors="replace")
                choices = desc.split(";", 1)[1].strip().split("|") if ";" in desc else []
                if choices:
                    self._defaults[key] = choices[0]
                i += 1
            return True
        if cmd == ENV_GET_VARIABLE:
            var = C.cast(data, C.POINTER(RetroVariable))[0]
            key = var.key.decode() if var.key else ""
            value = self._overrides.get(key, self._defaults.get(key))
            if value is None:
                return False
            buf = self._value_bufs.get(key)
            if buf is None:
                buf = self._value_bufs[key] = C.create_string_buffer(value.encode())
            C.cast(data, C.POINTER(C.c_void_p))[1] = C.addressof(buf)  # RetroVariable.value
            return True
        if cmd == ENV_GET_VARIABLE_UPDATE:
            C.cast(data, C.POINTER(C.c_bool))[0] = False
            return True
        if cmd == ENV_GET_LOG_INTERFACE:
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(self._log_cb_ref, C.c_void_p).value
            return True
        if cmd == ENV_GET_INPUT_BITMASKS:
            return True
        if cmd == ENV_GET_AUDIO_VIDEO_ENABLE:
            C.cast(data, C.POINTER(C.c_int))[0] = (1 if self.video_enabled else 0) | 2
            return True
        if cmd in (ENV_SET_SYSTEM_AV_INFO, ENV_SET_GEOMETRY):
            return True
        if cmd == ENV_SET_HW_RENDER:
            return False
        return False

    def option_values(self) -> dict[str, str]:
        merged = dict(self._defaults)
        merged.update(self._overrides)
        return merged

    # ---- callbacks ---------------------------------------------------------------------------------
    def _video(self, data, width, height, pitch):
        if data and self.video_enabled:  # NULL means "dupe last frame"
            self.last_video = (C.string_at(data, pitch * height), width, height, pitch)

    def _audio_one(self, left, right):
        self._audio.append(np.array([left, right], np.int16))

    def _audio_batch(self, ptr, frames):
        self._audio.append(np.ctypeslib.as_array(ptr, shape=(frames * 2,)).copy())
        return frames

    def _input_state(self, port, device, index, id_):
        if device != DEVICE_JOYPAD or port >= len(self._buttons):
            return 0
        mask = self._buttons[port]
        if id_ == JOYPAD_MASK:
            return mask & 0x7FFF if mask < 0x8000 else mask - 0x10000
        return (mask >> id_) & 1

    def _log(self, level, msg):
        if level >= 2 and msg:
            log.warning("core: %s", msg.decode(errors="replace").strip())

    # ---- operations --------------------------------------------------------------------------------
    def set_buttons(self, ports: tuple[int, ...]) -> None:
        self._buttons = tuple(ports)

    def take_audio(self) -> np.ndarray:
        if not self._audio:
            return np.zeros(0, np.int16)
        out = np.concatenate(self._audio)
        self._audio.clear()
        return out

    def load_game(self, path: Path) -> AVInfo:
        info = RetroSystemInfo()
        self.lib.retro_get_system_info(C.byref(info))
        game = RetroGameInfo(str(path).encode(), None, 0, None)
        if not self.lib.retro_load_game(C.byref(game)):
            raise EmulatorError(f"core refused content {path} (check BIOS and file paths)")
        av = RetroSystemAVInfo()
        self.lib.retro_get_system_av_info(C.byref(av))
        self._loaded = True
        self._av = AVInfo(av.timing.fps, av.timing.sample_rate, av.geometry.base_width, av.geometry.base_height)
        return self._av

    def run(self) -> None:
        self.lib.retro_run()

    def reset(self) -> None:
        self.lib.retro_reset()

    def serialize(self) -> bytes:
        n = self.lib.retro_serialize_size()
        buf = (C.c_uint8 * n)()
        if not self.lib.retro_serialize(buf, n):
            raise EmulatorError("core failed to save state")
        return bytes(buf)

    def unserialize(self, blob: bytes) -> None:
        buf = (C.c_uint8 * len(blob)).from_buffer_copy(blob)
        if not self.lib.retro_unserialize(buf, len(blob)):
            raise EmulatorError("core rejected the save state")

    def memory(self, region: int) -> tuple[int, int]:
        return int(self.lib.retro_get_memory_data(region) or 0), int(self.lib.retro_get_memory_size(region))

    def close(self) -> None:
        if self._loaded:
            self.lib.retro_unload_game()
            self._loaded = False
        self.lib.retro_deinit()
        global _LOADED_IN_PROCESS
        _LOADED_IN_PROCESS = False
