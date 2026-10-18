"""Composition root: builds every object from Config and wires them together."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from yomiplay.assist.companion import CompanionService
from yomiplay.assist.lexicon import FugashiTokenizer
from yomiplay.assist.profiles import ProfileLibrary
from yomiplay.config import Config
from yomiplay.core.protocol import Emulator
from yomiplay.core.proxy import EmulatorProxy, EmulatorSpec
from yomiplay.games.profile import GameProfile, load_profile
from yomiplay.games.serial import read_serial
from yomiplay.llm.claude_cli import ClaudeCLIBackend
from yomiplay.llm.protocol import LLMBackend
from yomiplay.runtime.clock import RealtimeClock
from yomiplay.runtime.inputs import HumanInput
from yomiplay.runtime.player import EmulatorFailed, Player, PlayerEvent
from yomiplay.runtime.replay import ReplayRecorder
from yomiplay.server.autoshutdown import AutoShutdown
from yomiplay.server.bridge import MediaBridge
from yomiplay.store import llm_choice
from yomiplay.store.logs import EventLog
from yomiplay.store.paths import DataPaths, config_root
from yomiplay.store.paths import data_root as default_data_root
from yomiplay.store.states import StateStore
from yomiplay.store.words import WordStore
from yomiplay.types import AVInfo

log = logging.getLogger("yomiplay.server")
REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "web"


@dataclass
class Runtime:
    cfg: Config
    paths: DataPaths
    emu: Emulator
    player: Player
    human: HumanInput
    bridge: MediaBridge
    profile: GameProfile
    serial: str | None
    av: AVInfo
    states: StateStore
    recorder: ReplayRecorder
    session_dir: Path
    paused_by_disconnect: bool = False
    media_clients: int = 0
    extra: dict = field(default_factory=dict)
    companion: CompanionService | None = None
    words: WordStore | None = None
    auto_shutdown: AutoShutdown | None = None  # only set by `yomiplay app`
    emulator_failed: str | None = None  # set (from the Player thread) when emulation stopped for good
    llm_backends: dict = field(default_factory=dict)  # "chat" -> backend whose model the UI may change


def llm_defaults(cfg: Config) -> dict[str, dict]:
    """Model and thinking per target from config.toml."""
    return {"chat": {"model": cfg.llm.model, "thinking": cfg.llm.thinking}}


def _build_emulator(cfg: Config, paths: DataPaths) -> Emulator:
    return EmulatorProxy(EmulatorSpec(kind="libretro", core_path=cfg.core.core_path,
                                      system_dir=cfg.core.bios_dir, save_dir=paths.memcards_dir))


def create_app(cfg: Config, content: Path, emulator: Emulator | None = None,
               data_root: Path | None = None, extra: dict | None = None, backend: LLMBackend | None = None,
               auto_shutdown: AutoShutdown | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        paths = DataPaths(data_root or default_data_root())
        emu = emulator or _build_emulator(cfg, paths)
        try:
            serial = read_serial(content)
            profile = load_profile(serial, [config_root() / "games", REPO_ROOT / "games"])  # user's own wins
            av = emu.load(content, {**profile.core_options, **cfg.core.options})
            if hasattr(emu, "set_game_serial"):
                emu.set_game_serial(serial)
        except BaseException:
            emu.close()  # do not leak the worker subprocess
            raise
        words: WordStore | None = None
        event_log: EventLog | None = None
        rt: Runtime | None = None
        started = False
        try:
            session_dir = paths.sessions_dir / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
            session_dir.mkdir(parents=True, exist_ok=True)
            bridge = MediaBridge(asyncio.get_running_loop())
            human = HumanInput()
            recorder = ReplayRecorder(emu.save_state(), emu.provenance, av.fps)

            def sink(event: PlayerEvent) -> None:  # Player thread
                if isinstance(event, EmulatorFailed) and rt is not None:
                    rt.emulator_failed = event.message
                bridge.sink(event)

            player = Player(emu, RealtimeClock(), human, sink, av.fps, recorder=recorder)
            words = WordStore(paths.words_db)
            event_log = EventLog(session_dir)
            event_log.append("session_start", serial=serial)  # chat history groups sessions by game
            # built before the Player thread starts, so touching emu.provenance here is safe
            choices = llm_choice.load(config_root() / "llm.json", llm_defaults(cfg))
            chat_llm = backend or ClaudeCLIBackend([cfg.llm.claude_bin], choices["chat"]["model"], cfg.llm.timeout_s,
                                                   choices["chat"]["thinking"])
            companion = CompanionService(
                chat_llm,
                ProfileLibrary([REPO_ROOT / "profiles", config_root() / "profiles"]),
                FugashiTokenizer(), words, event_log, profile, session_dir.name,
                json.dumps(emu.provenance.to_dict()))
            rt = Runtime(cfg, paths, emu, player, human, bridge, profile, serial, av,
                         StateStore(paths.states_dir(serial or "unknown")), recorder, session_dir,
                         extra=dict(extra or {}), companion=companion, words=words,
                         auto_shutdown=auto_shutdown, llm_backends={"chat": chat_llm})
            app.state.rt = rt
            for hook in rt.extra.get("on_startup", []):
                hook(rt)
            # nobody is watching yet: wait for the first page (media client) to resume the game
            player.pause()
            rt.paused_by_disconnect = True
            player.start()
            started = True
            if auto_shutdown is not None:
                auto_shutdown.start()
            yield
        finally:
            try:
                if auto_shutdown is not None:
                    await auto_shutdown.close()
                if started:
                    await asyncio.to_thread(rt.player.stop)
                if rt is not None:
                    try:
                        rt.recorder.save(rt.session_dir / "replay.ps1r")
                    except Exception:
                        log.exception("could not save replay")
                    await rt.companion.close()
            finally:
                if words is not None:
                    words.close()
                if event_log is not None:
                    event_log.close()
                emu.close()

    app = FastAPI(title="Yomiplay", lifespan=lifespan)
    from yomiplay.server.security import LocalOnlyMiddleware
    app.add_middleware(LocalOnlyMiddleware, port=cfg.server.port, extra_hosts=(cfg.server.host,))
    from yomiplay.server.routes import router
    app.include_router(router)
    from yomiplay.server.chat import router as chat_router
    app.include_router(chat_router)
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
