"""Local-only guard: the server answers only to localhost pages (no CSRF, no WebSocket hijacking, no DNS rebinding).

Every request must carry a local Host header (a rebinding attacker's page sends its own host name).
WebSockets and state-changing requests that carry an Origin must come from this server's own origin.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WILDCARD_BINDS = {"", "0.0.0.0", "::", "[::]"}


def _split_host(value: str) -> tuple[str, int | None]:
    name, sep, port = value.rpartition(":")
    if not sep or name.endswith(":") or (value.startswith("[") and not name.endswith("]")):
        return value.lower(), None  # no port (or a bare IPv6 address)
    try:
        return name.lower(), int(port)
    except ValueError:
        return value.lower(), None


def rejection(scope_type: str, method: str, headers: Mapping[str, str], port: int,
              extra_hosts: Iterable[str] = ()) -> str | None:
    """Return why a request must be refused, or None if it is allowed."""
    hosts = {*LOCAL_HOSTS, *(h.lower() for h in extra_hosts if h not in WILDCARD_BINDS)}
    host = headers.get("host")
    if not host:
        return "missing Host header"
    name, host_port = _split_host(host)
    if name not in hosts or (host_port is not None and host_port != port):
        return f"host {host!r} is not this local server"
    if scope_type == "websocket" or method.upper() not in SAFE_METHODS:
        origin = headers.get("origin")
        if origin is not None and origin.lower() not in {f"http://{h}:{port}" for h in hosts}:
            return f"origin {origin!r} is not this local server"
    return None


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, port: int, extra_hosts: Iterable[str] = ()):
        self.app, self.port, self.extra_hosts = app, port, tuple(extra_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            why = rejection(scope["type"], scope.get("method", "GET"), headers, self.port, self.extra_hosts)
            if why is not None:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008, "reason": why})
                else:
                    await PlainTextResponse(f"forbidden: {why}", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
