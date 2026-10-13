"""Scripted backend for tests: replays prepared event lists and records what was sent."""
from __future__ import annotations

from collections.abc import AsyncIterator

from yomiplay.llm.protocol import LLMError, LLMEvent, Message


class FakeConversation:
    def __init__(self, backend: FakeBackend):
        self.backend = backend

    async def send(self, msg: Message, schema: dict | None = None) -> AsyncIterator[LLMEvent]:
        self.backend.sent.append((msg, schema))
        if not self.backend.replies:
            yield LLMError("backend", "fake backend has no more replies")
            return
        for ev in self.backend.replies.pop(0):
            yield ev

    async def cancel(self) -> None:
        self.backend.cancelled += 1

    async def close(self) -> None:
        self.backend.closed += 1


class FakeBackend:
    name = "fake"

    def __init__(self, replies: list[list[LLMEvent]]):
        self.replies = list(replies)
        self.sent: list[tuple[Message, dict | None]] = []
        self.systems: list[str] = []
        self.cancelled = 0
        self.closed = 0

    async def open(self, system: str) -> FakeConversation:
        self.systems.append(system)
        return FakeConversation(self)
