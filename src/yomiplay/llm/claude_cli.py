"""Claude Code CLI backend: one long-lived `claude -p` process per conversation (no API key needed).

Locked down: no tools, no MCP servers, no user/project settings or hooks, empty working directory.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shutil
import signal
import tempfile
import time
from collections.abc import AsyncIterator

from yomiplay.llm.protocol import Delta, Final, LLMError, LLMEvent, Message, Progress, Usage

BASE_ARGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
             "--include-partial-messages", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
             "--setting-sources", ""]


PROGRESS_INTERVAL_S = 0.3  # at most one "receiving" update per this many seconds


def classify(text: str) -> str:
    t = text.lower()
    if "limit" in t or "429" in t:
        return "limit"
    if "login" in t or "auth" in t or "401" in t or "api key" in t:
        return "auth"
    return "backend"


class ClaudeCLIConversation:
    def __init__(self, backend: ClaudeCLIBackend, system: str):
        self.b, self.system = backend, system
        self._proc: asyncio.subprocess.Process | None = None
        self._schema_key: str | None = None
        self._cwd = tempfile.mkdtemp(prefix="yomiplay-claude-")
        self._lock = asyncio.Lock()
        self._cancelled = False
        self._stderr_tail = b""
        self._stderr_task: asyncio.Task | None = None

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """Keep the pipe empty (a chatty --verbose CLI would block otherwise); retain only the last 4 KB."""
        while chunk := await proc.stderr.read(4096):
            self._stderr_tail = (self._stderr_tail + chunk)[-4096:]

    async def _ensure(self, schema: dict | None) -> asyncio.subprocess.Process:
        # a new model or thinking level needs a new process (the old one's context is lost)
        key = json.dumps([schema, self.b.model, self.b.thinking], sort_keys=True)
        if self._proc and self._proc.returncode is None and key == self._schema_key:
            return self._proc
        await self._kill()
        args = [*self.b.command, *BASE_ARGS, "--system-prompt", self.system]
        if schema:
            args += ["--json-schema", json.dumps(schema)]
        if self.b.model:
            args += ["--model", self.b.model]
        env = None
        if self.b.thinking == "off":
            env = {**os.environ, "MAX_THINKING_TOKENS": "0"}
        elif self.b.thinking:
            args += ["--effort", self.b.thinking]
        self._proc = await asyncio.create_subprocess_exec(
            *args, cwd=self._cwd, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=16 * 1024 * 1024)
        self._schema_key = key
        self._stderr_tail = b""
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._proc))
        return self._proc

    @staticmethod
    def _encode(msg: Message) -> bytes:
        content = [{"type": "text", "text": msg.text}]
        for png in msg.images:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.b64encode(png).decode()}})
        return (json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n").encode()

    async def send(self, msg: Message, schema: dict | None = None) -> AsyncIterator[LLMEvent]:
        async with self._lock:
            self._cancelled = False
            consumed = False  # True once this turn's `result` (or a terminal condition) was fully read
            try:
                async for ev in self._turn(msg, schema):
                    if isinstance(ev, Final | LLMError):
                        consumed = True
                    yield ev
                consumed = True
            finally:
                if not consumed:  # consumer stopped early or was cancelled: drop the process with unread output
                    await self._kill()

    async def _turn(self, msg: Message, schema: dict | None) -> AsyncIterator[LLMEvent]:
        t0 = time.monotonic()
        try:
            proc = await self._ensure(schema)
        except OSError as e:  # includes FileNotFoundError: CLI not installed
            yield LLMError("backend", f"could not start claude CLI: {e}")
            return
        if self._cancelled:  # cancel() arrived while the process was spawning
            await self._kill()
            yield LLMError("cancelled", "cancelled")
            return
        try:
            proc.stdin.write(self._encode(msg))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the process already exited; its stderr is read at EOF below
        deadline = t0 + self.b.timeout_s
        started, received, last_progress = False, 0, float("-inf")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self._kill()
                yield LLMError("timeout", f"no answer within {self.b.timeout_s:.0f} s")
                return
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=min(remaining, 0.25))
            except TimeoutError:
                if self._cancelled:
                    yield LLMError("cancelled", "cancelled")
                    return
                continue
            except ValueError as e:  # a single output line exceeded the stream limit
                await self._kill()
                yield LLMError("backend", f"claude CLI produced an oversized line: {e}")
                return
            if self._cancelled:
                yield LLMError("cancelled", "cancelled")
                return
            if not line:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), 3)
                if self._stderr_task:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(asyncio.shield(self._stderr_task), 1)
                err = self._stderr_tail.decode(errors="replace").strip()
                self._proc = None
                yield LLMError(classify(err), err[-500:] or f"claude CLI exited with code {proc.returncode}")
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate stray non-JSON lines; a missing result is handled by EOF/timeout
            if not isinstance(ev, dict):
                continue
            kind = ev.get("type")
            if not started:  # the first line of a turn (system/init or the first stream event) means it is running
                started = True
                yield Progress("started")
            if kind == "stream_event":
                d = ev.get("event", {})
                delta = d.get("delta", {}) if d.get("type") == "content_block_delta" else {}
                piece = delta.get("text") if delta.get("type") == "text_delta" else (
                    delta.get("partial_json") if delta.get("type") == "input_json_delta" else None)
                if piece:
                    received += len(piece)
                    if delta["type"] == "text_delta" and not schema:
                        yield Delta(piece)
                    now = time.monotonic()
                    if now - last_progress >= PROGRESS_INTERVAL_S:
                        last_progress = now
                        yield Progress("receiving", received)
            elif kind == "result":
                text = ev.get("result") or ""
                if ev.get("is_error") or ev.get("subtype") != "success":
                    yield LLMError(classify(text), text or "the model returned an error")
                    return
                parsed = ev.get("structured_output")
                if schema and not isinstance(parsed, dict):
                    yield LLMError("schema", f"answer did not match the requested format: {text[:300]}")
                    return
                yield Final(text, parsed if schema else None)
                usage = ev.get("usage") or {}
                model = next(iter(ev.get("modelUsage") or {}), self.b.model or "claude")
                yield Usage(model, time.monotonic() - t0, usage.get("input_tokens"), usage.get("output_tokens"),
                            ev.get("total_cost_usd"))
                return

    async def cancel(self) -> None:
        self._cancelled = True
        await self._kill()

    async def _kill(self) -> None:
        p, self._proc = self._proc, None
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        if p and p.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGKILL)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(p.wait(), 3)

    async def close(self) -> None:
        await self._kill()
        shutil.rmtree(self._cwd, ignore_errors=True)


class ClaudeCLIBackend:
    name = "claude_cli"

    def __init__(self, command: list[str] | None = None, model: str | None = None, timeout_s: float = 90.0,
                 thinking: str | None = None):
        self.command = command or ["claude"]
        self.model = model
        self.thinking = thinking  # None (CLI default), "off", or an --effort level
        self.timeout_s = timeout_s

    async def open(self, system: str) -> ClaudeCLIConversation:
        return ClaudeCLIConversation(self, system)
