import asyncio
import threading

import numpy as np

from yomiplay.runtime.player import AudioReady, EmulatorFailed, FrameReady
from yomiplay.server.bridge import MediaBridge
from yomiplay.server.media import decode_header, encode_audio, encode_video, rate_from_fill
from yomiplay.types import Frame


def frame(i, w=320, h=240):
    return Frame(i, np.full((h, w, 4), i % 255, np.uint8))


def test_video_header_carries_size_changes():
    a = encode_video(frame(1, 350, 240))
    b = encode_video(frame(2, 640, 480))
    assert decode_header(a) == ("VID1", 1, 350, 240) and len(a) == 12 + 350 * 240 * 4
    assert decode_header(b) == ("VID1", 2, 640, 480)


def test_audio_encoding():
    m = encode_audio(np.arange(8, dtype=np.int16), 7)
    assert decode_header(m) == ("AUD1", 7, 4, 0) and len(m) == 12 + 16


def test_rate_from_fill_direction_and_clamp():
    assert rate_from_fill(80) == 1.0
    assert rate_from_fill(20) > 1.0 and rate_from_fill(200) < 1.0
    assert rate_from_fill(0) == 1.005 and rate_from_fill(10_000) == 0.995


async def test_latest_frame_wins_and_audio_drops_oldest():
    loop = asyncio.get_running_loop()
    br = MediaBridge(loop, audio_capacity=2)

    def produce():
        for i in range(1, 6):
            br.sink(FrameReady(frame(i)))
            br.sink(AudioReady(np.zeros(4, np.int16), i))

    t = threading.Thread(target=produce); t.start(); t.join()
    await asyncio.sleep(0.05)
    f = await asyncio.wait_for(br.next_frame(after_index=0), 1)
    assert f.index == 5
    got = [(await br.next_audio())[1] for _ in range(2)]
    assert got == [4, 5]


async def test_status_events_fan_out():
    loop = asyncio.get_running_loop()
    br = MediaBridge(loop)
    q = br.subscribe()
    threading.Thread(target=lambda: br.sink(EmulatorFailed("boom"))).start()
    ev = await asyncio.wait_for(q.get(), 1)
    assert ev.message == "boom"
    br.unsubscribe(q)


async def test_clear_audio_drops_stale_backlog():
    br = MediaBridge(asyncio.get_running_loop())
    br._push_audio(np.zeros(4, np.int16), 1)
    br._push_audio(np.zeros(4, np.int16), 2)
    br.clear_audio()
    br._push_audio(np.zeros(4, np.int16), 3)
    assert (await asyncio.wait_for(br.next_audio(), 1))[1] == 3
