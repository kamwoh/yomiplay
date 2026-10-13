"""Companion: ask about the screen, explain it as a study card, log every word that was read."""
from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pydantic import ValidationError

from yomiplay.assist.imaging import box_to_screen, png_bytes, prepare_for_model
from yomiplay.assist.lexicon import Tokenizer, content_words
from yomiplay.assist.profiles import ExplainProfile, ProfileLibrary, ProfileRef
from yomiplay.assist.prompts import SYSTEM_PROMPT, ask_prompt, explain_prompt
from yomiplay.assist.schemas import StudyCard, card_schema
from yomiplay.games.profile import GameProfile
from yomiplay.llm.protocol import Conversation, Final, LLMBackend, LLMError, LLMEvent, Message, Usage
from yomiplay.store.logs import EventLog
from yomiplay.store.words import Encounter, WordInput, WordStore
from yomiplay.types import Frame

MAX_ASK_TURNS = 20  # an Ask conversation keeps its history for follow-ups, up to this many turns
REPLACE_AFTER = {"backend", "limit"}  # errors after which a conversation is not trusted any more


def _place_boxes(parsed: object, rects: list[tuple[float, float, float, float]], w: int, h: int) -> object:
    """Replace each line's model box (0-1000 on the image the model saw) with full-screen fractions or None."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("lines"), list):
        return parsed
    lines = [{**ln, "box": box_to_screen(ln.get("box"), rects, w, h)} if isinstance(ln, dict) else ln
             for ln in parsed["lines"]]
    return {**parsed, "lines": lines}


@dataclass(frozen=True)
class CardReady:
    card_id: str
    card: StudyCard
    shot: str
    word_ids: list[list[int]]


@dataclass
class _CardCtx:
    card: StudyCard
    ref: ProfileRef
    frame_index: int
    shot: str
    language: str


class CompanionService:
    def __init__(self, backend: LLMBackend, profiles: ProfileLibrary, tokenizer: Tokenizer, words: WordStore,
                 log: EventLog, game: GameProfile, session: str, provenance_json: str):
        self.backend, self.profiles, self.tok, self.words, self.log = backend, profiles, tokenizer, words, log
        self.game, self.session, self.prov = game, session, provenance_json
        self._convs: dict[tuple[str, str], Conversation] = {}
        self._turns: dict[tuple[str, str], int] = {}
        self._active: dict[str, Conversation] = {}
        self._cards: dict[str, _CardCtx] = {}

    async def _conv(self, chat_id: str, kind: str, fresh: bool) -> Conversation:
        key = (chat_id, kind)
        if key in self._convs and (fresh or self._turns[key] >= MAX_ASK_TURNS):
            await self._drop(key, self._convs[key])
        if key not in self._convs:
            self._convs[key] = await self.backend.open(SYSTEM_PROMPT)
            self._turns[key] = 0
        self._active[chat_id] = self._convs[key]
        return self._convs[key]

    async def _drop(self, key: tuple[str, str], conv: Conversation) -> None:
        if self._convs.get(key) is conv:
            del self._convs[key], self._turns[key]
        with contextlib.suppress(Exception):
            await conv.close()

    async def _send(self, chat_id: str, kind: str, msg: Message, schema: dict | None = None,
                    fresh: bool = False) -> AsyncIterator[LLMEvent]:
        """One turn. fresh=True starts a new conversation (closing the old one) instead of continuing it."""
        key = (chat_id, kind)
        conv = await self._conv(chat_id, kind, fresh)
        self._turns[key] += 1
        broken = False
        async for ev in conv.send(msg, schema=schema):
            broken |= isinstance(ev, LLMError) and ev.kind in REPLACE_AFTER
            yield ev
        if broken:
            await self._drop(key, conv)

    def _profile(self, name: str) -> ExplainProfile | None:
        try:
            return self.profiles.get(name)
        except KeyError:
            return None

    async def ask(self, chat_id: str, question: str, frame: Frame | None,
                  profile_name: str) -> AsyncIterator[LLMEvent]:
        profile = self._profile(profile_name)
        if profile is None:
            yield LLMError("backend", f"unknown explain profile '{profile_name}'")
            return
        images = (prepare_for_model(frame.rgba, [], scale=2),) if frame is not None else ()
        answer, usage = "", None
        try:
            async for ev in self._send(chat_id, "ask", Message("user", ask_prompt(profile, self.game, question), images)):
                if isinstance(ev, Final):
                    answer = ev.text
                elif isinstance(ev, Usage):
                    usage = ev
                yield ev
        finally:
            if answer:
                self.log.append("ask", question=question, answer=answer, model=usage.model if usage else None,
                                latency_s=usage.latency_s if usage else None,
                                frame_index=frame.index if frame else None, profile=profile.name)

    async def explain(self, chat_id: str, frame: Frame, profile_name: str) -> AsyncIterator[LLMEvent | CardReady]:
        profile = self._profile(profile_name)
        if profile is None:
            yield LLMError("backend", f"unknown explain profile '{profile_name}'")
            return
        shot = self.log.save_png(png_bytes(frame.rgba), frame.index)
        image = prepare_for_model(frame.rgba, self.game.dialogue_rects, scale=3)
        prompt = explain_prompt(profile, self.game)
        if profile.card == "free":  # a tutoring turn: part of the Ask conversation
            async for ev in self._send(chat_id, "ask", Message("user", prompt, (image,))):
                yield ev
            return
        ref = self.profiles.ref(profile)
        # an explanation needs no history: each one gets a new conversation (no growing image backlog)
        async for ev in self._send(chat_id, "explain", Message("user", prompt, (image,)),
                                   schema=card_schema(profile.target_languages, profile.source_language), fresh=True):
            if isinstance(ev, Final):
                try:
                    h, w = frame.rgba.shape[:2]
                    card = StudyCard.model_validate(_place_boxes(ev.parsed or {}, self.game.dialogue_rects, w, h))
                except ValidationError as e:
                    yield LLMError("schema", f"study card was malformed: {e.errors()[0]['msg']}")
                    return
                card_id = uuid.uuid4().hex[:12]
                self._cards[card_id] = _CardCtx(card, ref, frame.index, shot, profile.source_language)
                word_ids = [self._record_line(card_id, i, line.source) for i, line in enumerate(card.lines)]
                self.log.append("explain", card_id=card_id, card=card.model_dump(), shot=shot,
                                frame_index=frame.index, profile=ref.name, profile_sha=ref.sha256)
                yield CardReady(card_id, card, shot, word_ids)
            else:
                yield ev

    def _record_line(self, card_id: str, line_index: int, text: str) -> list[int]:
        ctx = self._cards[card_id]
        meanings = {w.word: w.meanings for w in ctx.card.words}
        tokens = content_words(self.tok.tokenize(text)) if text.strip() else []
        inputs = [WordInput(ctx.language, t.key, t.lemma, t.reading, t.pos,
                            meanings.get(t.lemma) or meanings.get(t.surface) or {}) for t in tokens]
        if not inputs:
            return []
        enc = Encounter(card_id, line_index, text, self.session, ctx.frame_index, ctx.shot, ctx.ref.name,
                        ctx.ref.sha256, self.prov)
        return self.words.record(inputs, enc)

    def correct_line(self, card_id: str, line_index: int, text: str) -> list[int]:
        if card_id not in self._cards:
            raise KeyError(card_id)
        if not 0 <= line_index < len(self._cards[card_id].card.lines):
            raise IndexError(line_index)
        self.words.clear_line(card_id, line_index)
        ctx = self._cards[card_id]
        if 0 <= line_index < len(ctx.card.lines):
            ctx.card.lines[line_index].source = text
        self.log.append("correct_line", card_id=card_id, line_index=line_index, text=text)
        return self._record_line(card_id, line_index, text)

    def star(self, word_id: int, starred: bool) -> None:
        self.words.star(word_id, starred)

    async def cancel(self, chat_id: str) -> None:
        conv = self._active.get(chat_id)
        if conv is not None:
            await conv.cancel()

    async def close(self) -> None:
        for key, c in list(self._convs.items()):
            await self._drop(key, c)
