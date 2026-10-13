"""Companion endpoints: chat WebSocket, explain profiles, words, screenshots, card corrections."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from yomiplay.assist.companion import CardReady
from yomiplay.assist.imaging import png_bytes
from yomiplay.llm.protocol import Delta, Final, LLMError, Progress, Usage
from yomiplay.store.history import SESSION_RE, read_history

router = APIRouter()
log = logging.getLogger("yomiplay.server")
SHOT_RE = re.compile(r"^shot-\d+\.png$")


def rt(req):
    return req.app.state.rt


class StarBody(BaseModel):
    starred: bool


class LineBody(BaseModel):
    text: str


@router.get("/api/profiles")
async def profiles(request: Request):
    r = rt(request)
    lib = r.companion.profiles
    return {"default": r.cfg.companion.default_profile,
            "profiles": [{"name": p.name, "title": p.title or p.name, "card": p.card,
                          "target_languages": p.target_languages} for p in lib.list()],
            "problems": lib.problems()}


@router.get("/api/words")
async def words(request: Request, filter: str = "all", sort: str = "count", session: str | None = None):
    r = rt(request)
    if filter not in ("all", "starred", "session") or sort not in ("count", "recent"):
        raise HTTPException(400, "filter must be all|starred|session and sort count|recent")
    if session is not None and not SESSION_RE.fullmatch(session):
        raise HTTPException(400, "session must be a session name like 20260101-120000")
    return [asdict(w) for w in r.words.list(filter=filter, session=session or r.session_dir.name, sort=sort)]


@router.post("/api/words/{word_id}/star")
async def star(word_id: int, body: StarBody, request: Request):
    rt(request).companion.star(word_id, body.starred)
    return {"ok": True}


@router.get("/api/words/{word_id}/encounters")
async def encounters(word_id: int, request: Request):
    return [asdict(e) for e in rt(request).words.encounters(word_id)]


@router.get("/api/shots/{name}")
async def shot(name: str, request: Request):
    r = rt(request)
    if not SHOT_RE.fullmatch(name):
        raise HTTPException(404)
    others = sorted((d for d in r.paths.sessions_dir.iterdir() if d != r.session_dir), reverse=True)
    for d in [r.session_dir, *others]:  # current session first
        p = d / "shots" / name
        if p.exists():
            return FileResponse(p, media_type="image/png")
    raise HTTPException(404)


@router.post("/api/cards/{card_id}/lines/{index}")
async def correct(card_id: str, index: int, body: LineBody, request: Request):
    try:
        ids = rt(request).companion.correct_line(card_id, index, body.text)
    except KeyError:
        raise HTTPException(404, "unknown card (cards are kept for the current session only)")
    except IndexError:
        raise HTTPException(400, "line index out of range")
    return {"word_ids": ids}


@router.get("/api/history")
async def history(request: Request, limit: int = Query(50, ge=1, le=500), before: str | None = None):
    """Chat history across this game's server sessions, newest page first (see store.history)."""
    r = rt(request)
    try:
        return await asyncio.to_thread(read_history, r.paths.sessions_dir, r.session_dir, r.serial, limit, before)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/api/screenshot.png")
async def screenshot(request: Request):
    f = rt(request).player.latest_frame()
    if f is None:
        raise HTTPException(409, "no frame yet")
    return Response(png_bytes(f.rgba), media_type="image/png")


def _to_json(ev) -> dict | None:
    if isinstance(ev, Delta):
        return {"type": "delta", "text": ev.text}
    if isinstance(ev, Progress):
        return {"type": "progress", "stage": ev.stage, "chars": ev.chars}
    if isinstance(ev, CardReady):
        return {"type": "card", "card_id": ev.card_id, "card": ev.card.model_dump(), "shot": ev.shot,
                "word_ids": ev.word_ids}
    if isinstance(ev, Final):
        return {"type": "final", "text": ev.text} if ev.parsed is None else None
    if isinstance(ev, Usage):
        return {"type": "usage", "model": ev.model, "latency_s": round(ev.latency_s, 2), "cost_usd": ev.cost_usd}
    if isinstance(ev, LLMError):
        return {"type": "error", "kind": ev.kind, "message": ev.message}
    return None


@router.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    r = rt(ws)
    running: dict[str, asyncio.Task] = {}

    async def run(msg: dict):
        chat_id = str(msg.get("chat_id", "main"))
        profile = msg.get("profile") or r.cfg.companion.default_profile
        try:
            if r.cfg.companion.pause_while_reading:
                await asyncio.to_thread(r.player.pause)
            frame = r.player.latest_frame()
            if msg["type"] == "explain":
                if frame is None:
                    await ws.send_json({"type": "error", "kind": "backend", "message": "no game frame yet"})
                    return
                stream = r.companion.explain(chat_id, frame, profile)
            else:
                stream = r.companion.ask(chat_id, msg.get("text", ""), frame if msg.get("with_screen", True) else None,
                                         profile)
            async for ev in stream:
                out = _to_json(ev)
                if out is not None:
                    await ws.send_json(out)
        except Exception as e:  # never let a request die silently: the user must see why
            log.exception("chat request failed")
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "error", "kind": "backend", "message": f"{type(e).__name__}: {e}"})
        finally:
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "done", "chat_id": chat_id})

    try:
        while True:
            try:
                msg = await ws.receive_json()
                if not isinstance(msg, dict):
                    raise TypeError("not an object")
            except WebSocketDisconnect:
                raise
            except (ValueError, TypeError):  # includes JSONDecodeError
                await ws.send_json({"type": "error", "kind": "backend", "message": "bad request"})
                continue
            chat_id = str(msg.get("chat_id", "main"))
            if msg.get("type") == "cancel":
                await r.companion.cancel(chat_id)
                continue
            if msg.get("type") in ("ask", "explain"):
                prev = running.get(chat_id)
                if prev and not prev.done():
                    await ws.send_json({"type": "error", "kind": "backend",
                                        "message": "still answering the previous request; cancel it first"})
                    continue
                running[chat_id] = asyncio.create_task(run(msg))
    except WebSocketDisconnect:
        pass
    finally:
        for t in running.values():
            t.cancel()
        await asyncio.gather(*running.values(), return_exceptions=True)
