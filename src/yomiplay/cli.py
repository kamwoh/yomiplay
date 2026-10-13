"""Command line: serve the app, check the setup, verify replays."""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from yomiplay.config import load_config


def _print_checks(checks: list[tuple[bool, str]]) -> bool:
    for good, msg in checks:
        print(("  ok   " if good else "  FIX  ") + msg)
    return all(good for good, _ in checks)


def emulator_checks(cfg) -> list[tuple[bool, str]]:
    from yomiplay.core.emulator import check_bios
    c = cfg.core.core_path
    b = cfg.core.bios_dir
    found = check_bios(b) if b and b.exists() else []
    return [(bool(c and c.exists()), f"core: {c or 'not set'} (set [core].core_path to your mednafen_psx_libretro.so)"),
            (bool(found), f"BIOS in {b or 'not set'}: {', '.join(found) or 'no known BIOS file found'}")]


def cmd_doctor(cfg) -> int:
    exe = shutil.which(cfg.llm.claude_bin)
    ok = _print_checks([*emulator_checks(cfg),
                        (exe is not None, f"claude CLI: {exe or 'not found on PATH'} (install Claude Code and log in)")])
    return 0 if ok else 1


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def open_command(url: str, wsl: bool) -> list[str] | None:
    """Command that opens `url` in the default browser; None means use Python's webbrowser module."""
    return ["cmd.exe", "/c", "start", url] if wsl else None


def open_ui(url: str, wsl: bool | None = None, run=subprocess.run, open_browser=webbrowser.open) -> None:
    """Open the UI in the default browser. Never raises: the user can still open the printed URL by hand."""
    try:
        cmd = open_command(url, is_wsl() if wsl is None else wsl)
        if cmd is None:
            open_browser(url)
        else:
            run(cmd, check=False, capture_output=True, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"could not open a browser ({e}); open {url} yourself")


def _open_when_listening(port: int, url: str, stop: threading.Event, opener, max_wait_s: float = 300.0) -> None:
    """Open the UI once the port accepts connections (a slow core or BIOS load can take a while)."""
    deadline = time.monotonic() + max_wait_s
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        except OSError:
            stop.wait(0.1)
            continue
        opener(url)
        return


def _run_server(cfg, content: Path, fake: bool, app_mode: bool, opener=None) -> int:
    import uvicorn

    from yomiplay.server.app import create_app
    emu = None
    if fake:
        from yomiplay.core.fake import FakeEmulator
        emu = FakeEmulator()
    elif not content.exists():
        print(f"game not found: {content}", file=sys.stderr)
        return 2
    elif not all(good for good, _ in emulator_checks(cfg)):
        _print_checks(emulator_checks(cfg))
        print("cannot start: fix the lines marked FIX in your config (see `yomiplay doctor`)", file=sys.stderr)
        return 2
    opener = opener or open_ui  # looked up at call time so tests can stub it
    extra: dict = {}
    auto = None
    if app_mode:
        from yomiplay.server.autoshutdown import AutoShutdown

        def trigger(reason: str) -> None:
            if reason == "idle":
                print(f"tab closed: shutting down after {cfg.app.idle_shutdown_s:g} s without a client")
            else:
                print(f"no tab connected within {cfg.app.first_connect_timeout_s:g} s: shutting down")
            extra["request_shutdown"]()
        auto = AutoShutdown(cfg.app.idle_shutdown_s, cfg.app.first_connect_timeout_s, trigger)
    app = create_app(cfg, content, emulator=emu, extra=extra, auto_shutdown=auto)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.server.host, port=cfg.server.port, log_level="warning"))
    extra["request_shutdown"] = lambda: setattr(server, "should_exit", True)  # POST /api/quit
    url = f"http://localhost:{cfg.server.port}"
    stop = threading.Event()
    if app_mode:
        print(f"yomiplay app: {url}")
        threading.Thread(target=_open_when_listening, args=(cfg.server.port, url, stop, opener),
                         daemon=True).start()
    else:
        print(f"Open {url} in your browser")
    try:
        server.run()
    finally:
        stop.set()
    if app_mode:
        print("yomiplay app: server stopped")
    return 0


def cmd_serve(cfg, content: Path, fake: bool) -> int:
    return _run_server(cfg, content, fake, app_mode=False)


def cmd_app(cfg, content: Path, fake: bool) -> int:
    return _run_server(cfg, content, fake, app_mode=True)


def cmd_verify(cfg, replay: Path, content: Path) -> int:
    from yomiplay.core.proxy import EmulatorProxy, EmulatorSpec
    from yomiplay.runtime.replay import Replay, verify_replay
    from yomiplay.store.paths import DataPaths, data_root
    r = Replay.load(replay)
    emu = EmulatorProxy(EmulatorSpec("libretro", cfg.core.core_path, cfg.core.bios_dir,
                                     DataPaths(data_root()).root / "verify-memcards", persist_saves=False))
    try:
        emu.load(content, r.provenance.core_options)
        bad = verify_replay(emu, r)
    finally:
        emu.close()
    print("deterministic" if not bad else f"diverged at frames {bad[:10]}")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    # --config is accepted both before and after the subcommand; SUPPRESS keeps one from clobbering the other
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog="yomiplay", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", parents=[common]); s.add_argument("content", type=Path); s.add_argument("--fake", action="store_true")
    ap_ = sub.add_parser("app", parents=[common]); ap_.add_argument("content", type=Path); ap_.add_argument("--fake", action="store_true")
    sub.add_parser("doctor", parents=[common])
    v = sub.add_parser("verify-replay", parents=[common]); v.add_argument("replay", type=Path); v.add_argument("content", type=Path)
    a = ap.parse_args(argv)
    cfg = load_config(getattr(a, "config", None))
    if a.cmd == "doctor":
        return cmd_doctor(cfg)
    if a.cmd == "serve":
        return cmd_serve(cfg, a.content, a.fake)
    if a.cmd == "app":
        return cmd_app(cfg, a.content, a.fake)
    return cmd_verify(cfg, a.replay, a.content)


if __name__ == "__main__":
    sys.exit(main())
