from yomiplay.llm.fake import FakeBackend
from yomiplay.llm.protocol import Delta, Final, LLMBackend, Message, Usage


async def test_fake_backend_replays_and_records():
    be = FakeBackend([[Delta("Hel"), Delta("lo"), Final("Hello", None), Usage("fake", 0.1)]])
    assert isinstance(be, LLMBackend)
    conv = await be.open("system text")
    events = [e async for e in conv.send(Message("user", "hi", (b"png",)), schema={"type": "object"})]
    assert [type(e).__name__ for e in events] == ["Delta", "Delta", "Final", "Usage"]
    assert be.systems == ["system text"]
    msg, schema = be.sent[0]
    assert msg.images == (b"png",) and schema == {"type": "object"}
    await conv.close()


async def test_fake_backend_out_of_replies_reports_error():
    conv = await FakeBackend([]).open("s")
    events = [e async for e in conv.send(Message("user", "hi"))]
    assert events[0].kind == "backend"
