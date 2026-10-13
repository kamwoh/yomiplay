"""HTTP and WebSocket endpoints for play: status, pause, save states, media and input streams."""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from yomiplay.runtime.player import EmulatorFailed, StatusChanged
from yomiplay.server.app import WEB_DIR
from yomiplay.server.media import encode_audio, encode_video, rate_from_fill
from yomiplay.store import controls as ctl
from yomiplay.store.paths import config_root
from yomiplay.store.states import SlotCorrupt, StateMismatch

router = APIRouter()


def rt(req: Request | WebSocket):
    return req.app.state.rt


@router.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


def controls_path():
    return config_root() / "controls.json"


@router.get("/api/status")
async def status(request: Request):
    r = rt(request)
    keys, _ = ctl.load(controls_path(), r.cfg.keys.mapping)
    f = r.player.latest_frame()
    return {"game": r.profile.name, "serial": r.serial, "paused": r.player.paused,
            "frame_index": f.index if f else 0, "fps": r.av.fps, "keys": keys,
            "emulator_failed": r.emulator_failed}


@router.post("/api/pause")
async def pause(request: Request):
    await asyncio.to_thread(rt(request).player.pause)
    return {"paused": True}


@router.post("/api/resume")
async def resume(request: Request):
    r = rt(request)
    r.paused_by_disconnect = False
    await asyncio.to_thread(r.player.resume)
    return {"paused": False}


class ControlsBody(BaseModel):
    keys: dict
    pad: dict


@router.get("/api/controls")
async def get_controls(request: Request):
    r = rt(request)
    keys, pad = ctl.load(controls_path(), r.cfg.keys.mapping)
    return {"keys": keys, "pad": pad, "buttons": ctl.BUTTONS,
            "defaults": {"keys": r.cfg.keys.mapping, "pad": ctl.default_pad()}}


@router.put("/api/controls")
async def put_controls(body: ControlsBody, request: Request):
    try:
        keys, pad = ctl.validate(body.keys, body.pad)
    except ctl.InvalidControls as e:
        raise HTTPException(400, str(e))
    try:
        await asyncio.to_thread(ctl.save, controls_path(), keys, pad)
    except OSError as e:
        raise HTTPException(500, f"could not save controls: {e}")
    return {"keys": keys, "pad": pad}


@router.post("/api/reset")
async def reset(request: Request):
    r = rt(request)
    await asyncio.wrap_future(r.player.submit(lambda emu: emu.reset()))  # emulator calls belong to the Player thread
    r.companion.log.append("reset")
    return {"ok": True}


@router.post("/api/quit")
async def quit_server(request: Request, tasks: BackgroundTasks):
    """Stop the whole server cleanly (the lifespan shutdown saves the replay and flushes the memory card)."""
    hook = rt(request).extra.get("request_shutdown")
    if hook is not None:
        tasks.add_task(hook)  # runs after the response has been sent
    return {"ok": True}


@router.get("/api/states")
async def list_states(request: Request):
    return [s.__dict__ for s in rt(request).states.list()]


@router.post("/api/states/{slot}")
async def save_state(slot: int, request: Request):
    r = rt(request)
    frame = r.player.latest_frame()
    if frame is None:
        raise HTTPException(409, "no frame yet")
    # emulator calls (including provenance, which is a worker round-trip) must run on the Player
    # thread: the proxy pipe is not safe for concurrent use.
    blob, prov = await asyncio.wrap_future(r.player.submit(lambda emu: (emu.save_state(), emu.provenance)))
    try:
        info = await asyncio.to_thread(r.states.put, slot, blob, frame, prov)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return info.__dict__


@router.post("/api/states/{slot}/load")
async def load_state(slot: int, request: Request):
    r = rt(request)
    prov = await asyncio.wrap_future(r.player.submit(lambda emu: emu.provenance))
    try:
        blob = await asyncio.to_thread(r.states.get, slot, prov)
    except FileNotFoundError:
        raise HTTPException(404, f"slot {slot} is empty")
    except (StateMismatch, SlotCorrupt) as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await asyncio.wrap_future(r.player.submit(lambda emu: emu.load_state(blob)))
    return {"ok": True}


@router.get("/api/states/{slot}/thumb.png")
async def thumb(slot: int, request: Request):
    p = rt(request).states.thumb_path(slot)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@router.websocket("/ws/media")
async def media(ws: WebSocket):
    await ws.accept()
    r = rt(ws)
    r.media_clients += 1
    if r.auto_shutdown is not None:
        r.auto_shutdown.on_connect()
    r.bridge.clear_audio()
    events = r.bridge.subscribe()  # before the check below, so a failure in between is not missed
    if r.emulator_failed is not None:
        await ws.send_json({"type": "emulator_failed", "message": r.emulator_failed})
    if r.paused_by_disconnect:
        r.paused_by_disconnect = False
        # shielded: once the flag is cleared the resume must happen even if this handler is cancelled
        await asyncio.shield(asyncio.to_thread(r.player.resume))

    async def send_video():
        last = 0
        while True:
            f = await r.bridge.next_frame(last)
            last = f.index
            await ws.send_bytes(encode_video(f))

    async def send_audio():
        while True:
            pcm, idx = await r.bridge.next_audio()
            await ws.send_bytes(encode_audio(pcm, idx))

    async def send_events():
        while True:
            ev = await events.get()
            if isinstance(ev, StatusChanged):
                await ws.send_json({"type": "status", "paused": ev.paused})
            elif isinstance(ev, EmulatorFailed):
                await ws.send_json({"type": "emulator_failed", "message": ev.message})

    async def receive():
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "audio_fill":
                r.player.set_rate_hint(rate_from_fill(float(msg.get("ms", 80))))

    tasks = [asyncio.create_task(c()) for c in (send_video, send_audio, send_events, receive)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(BaseException):
                await t
        r.bridge.unsubscribe(events)
        r.media_clients -= 1
        if r.auto_shutdown is not None:
            r.auto_shutdown.on_disconnect(r.media_clients)
        if r.media_clients == 0 and not r.player.paused:
            r.paused_by_disconnect = True
            await asyncio.shield(asyncio.to_thread(r.player.pause))  # also when the handler is being cancelled


@router.websocket("/ws/input")
async def input_ws(ws: WebSocket):
    await ws.accept()
    r = rt(ws)
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                raise
            except ValueError:  # not JSON (JSONDecodeError is a ValueError): ignore
                continue
            try:
                if msg.get("type") == "buttons":
                    r.human.set_port(int(msg.get("port", 0)), int(msg.get("mask", 0)))
            except (AttributeError, TypeError, ValueError):
                continue
    except WebSocketDisconnect:
        pass
    finally:
        r.human.set_port(0, 0)  # release all buttons when the page goes away or the socket fails
