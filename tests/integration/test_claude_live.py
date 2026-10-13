import pytest

from yomiplay.llm.claude_cli import ClaudeCLIBackend
from yomiplay.llm.protocol import Final, Message, Progress

pytestmark = pytest.mark.live_llm


async def test_real_cli_answers_with_schema():
    conv = await ClaudeCLIBackend(timeout_s=120).open("Answer briefly.")
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    events = [e async for e in conv.send(Message("user", "What is 2 + 3? Answer with the number."), schema)]
    final = [e for e in events if isinstance(e, Final)]
    assert final and "5" in final[0].parsed["answer"]
    assert Progress("started") in events and any(e.stage == "receiving" and e.chars > 0 for e in events
                                                 if isinstance(e, Progress))
    await conv.close()
