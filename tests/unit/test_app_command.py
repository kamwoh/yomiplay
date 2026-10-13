import asyncio
import socket
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from yomiplay import cli
from yomiplay.cli import _open_when_listening, is_wsl, main, open_command, open_ui
from yomiplay.config import AppConfig, Config, ServerConfig, load_config
from yomiplay.core.fake import FakeEmulator
from yomiplay.server.app import create_app
from yomiplay.server.autoshutdown import AutoShutdown


def make(tmp_path, auto):
    cfg = Config(server=ServerConfig(host="testserver"))
    return TestClient(create_app(cfg, Path("fake.cue"), emulator=FakeEmulator(), data_root=tmp_path, auto_shutdown=auto))


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_idle_shutdown_fires_after_last_client_leaves(tmp_path):
    fired = []
    with make(tmp_path, AutoShutdown(0.2, 30, fired.append)) as c:
        with c.websocket_connect("/ws/media"):
            time.sleep(0.4)
            assert fired == []  # a connected client keeps the app alive
        assert wait_for(lambda: fired == ["idle"])


def test_reconnect_before_expiry_cancels_timer(tmp_path):
    fired = []
    with make(tmp_path, AutoShutdown(1.0, 30, fired.append)) as c:
        with c.websocket_connect("/ws/media"):
            pass
        time.sleep(0.1)
        with c.websocket_connect("/ws/media"):
            time.sleep(0.5)
            assert fired == []


def test_two_clients_only_last_leaving_starts_timer(tmp_path):
    fired = []
    with make(tmp_path, AutoShutdown(0.2, 30, fired.append)) as c, c.websocket_connect("/ws/media"):
        with c.websocket_connect("/ws/media"):
            pass
        time.sleep(0.5)
        assert fired == []


def test_startup_grace_fires_without_client(tmp_path):
    fired = []
    with make(tmp_path, AutoShutdown(30, 0.2, fired.append)) as c:
        assert wait_for(lambda: fired == ["no_client"])
        c.get("/api/status")


def test_first_connect_cancels_startup_grace(tmp_path):
    fired = []
    with make(tmp_path, AutoShutdown(30, 0.3, fired.append)) as c, c.websocket_connect("/ws/media"):
        time.sleep(0.6)
        assert fired == []


def test_serve_mode_never_auto_shuts_down(tmp_path):
    with make(tmp_path, None) as c:
        with c.websocket_connect("/ws/media"):
            pass
        time.sleep(0.3)
        assert c.app.state.rt.auto_shutdown is None
        assert c.get("/api/status").status_code == 200


def test_close_cancels_pending_timer_cleanly():
    async def go():
        a = AutoShutdown(30, 30, lambda r: None)
        a.start()
        task = a._task
        await a.close()
        assert task.cancelled() and a._task is None
    asyncio.run(go())


def test_app_config_defaults_and_toml(tmp_path):
    assert AppConfig().idle_shutdown_s == 10.0 and AppConfig().first_connect_timeout_s == 60.0
    f = tmp_path / "c.toml"
    f.write_text("[app]\nidle_shutdown_s = 2.5\nfirst_connect_timeout_s = 7\n")
    cfg = load_config(f)
    assert cfg.app.idle_shutdown_s == 2.5 and cfg.app.first_connect_timeout_s == 7.0
    assert load_config(tmp_path / "none.toml").app.idle_shutdown_s == 10.0


def test_open_command_selection():
    assert open_command("http://localhost:1", True) == ["cmd.exe", "/c", "start", "http://localhost:1"]
    assert open_command("http://localhost:1", False) is None


def test_open_ui_wsl_runs_cmd_start():
    calls = []
    open_ui("http://localhost:1", wsl=True, run=lambda cmd, **k: calls.append(cmd), open_browser=calls.append)
    assert calls == [["cmd.exe", "/c", "start", "http://localhost:1"]]


def test_open_ui_missing_cmd_does_not_crash():
    def run(cmd, **k):
        raise FileNotFoundError
    open_ui("http://localhost:1", wsl=True, run=run)


def test_open_ui_elsewhere_uses_webbrowser():
    opened = []
    open_ui("http://localhost:1", wsl=False, run=lambda *a, **k: 1 / 0, open_browser=opened.append)
    assert opened == ["http://localhost:1"]


def test_is_wsl_env(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert is_wsl() is True


def test_is_wsl_false_and_proc_version(monkeypatch, tmp_path):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "Linux version 5 (Microsoft@x)" if str(self) == "/proc/version" else real(self, *a, **k))
    assert is_wsl() is True
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "Linux version 6 (gcc)" if str(self) == "/proc/version" else real(self, *a, **k))
    assert is_wsl() is False

    def boom(self, *a, **k):
        raise OSError
    monkeypatch.setattr(Path, "read_text", boom)
    assert is_wsl() is False


def test_close_prevents_rearming():
    async def go():
        a = AutoShutdown(0.01, 0.01, lambda r: None)
        await a.close()
        a.on_disconnect(0)
        a.start()
        assert a._task is None
    asyncio.run(go())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_open_when_listening_waits_for_real_socket():
    port = free_port()
    opened, stop = [], threading.Event()
    t = threading.Thread(target=_open_when_listening, args=(port, "u", stop, opened.append), daemon=True)
    t.start()
    time.sleep(0.4)
    assert opened == []  # nothing listens yet
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", port))
        srv.listen()
        t.join(3)
    assert opened == ["u"] and not t.is_alive()


def test_open_when_listening_stops_on_event():
    stop = threading.Event()
    t = threading.Thread(target=_open_when_listening, args=(free_port(), "u", stop, lambda u: 1 / 0), daemon=True)
    t.start()
    stop.set()
    t.join(3)
    assert not t.is_alive()


def test_app_command_end_to_end_fake(tmp_path, monkeypatch, capsys):
    import websockets.sync.client as wsc
    port = free_port()
    cfgf = tmp_path / "c.toml"
    cfgf.write_text(f"[server]\nport = {port}\n[app]\nidle_shutdown_s = 0.5\nfirst_connect_timeout_s = 30\n")
    monkeypatch.setenv("YOMIPLAY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("YOMIPLAY_CONFIG_DIR", str(tmp_path / "cfg"))
    opened, listening_at_open = [], []

    def opener(url):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            listening_at_open.append(True)
        except OSError:
            listening_at_open.append(False)
        opened.append(url)
    monkeypatch.setattr(cli, "open_ui", opener)
    result = []
    t = threading.Thread(target=lambda: result.append(main(["app", "x.cue", "--fake", "--config", str(cfgf)])), daemon=True)
    t.start()
    assert wait_for(lambda: opened, 20)
    assert opened == [f"http://localhost:{port}"] and listening_at_open == [True]
    with wsc.connect(f"ws://127.0.0.1:{port}/ws/media", origin=f"http://localhost:{port}") as ws:
        ws.recv(timeout=5)
    t.join(20)
    assert not t.is_alive() and result == [0]
    assert opened == [f"http://localhost:{port}"]  # exactly once
    assert "shutting down" in capsys.readouterr().out
