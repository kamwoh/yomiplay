import asyncio
import json
import sys
from pathlib import Path

import pytest

from yomiplay.llm.claude_cli import ClaudeCLIBackend
from yomiplay.llm.protocol import Delta, Final, LLMError, Message, Progress, Usage

FAKE = [sys.executable, str(Path(__file__).parents[1] / "fixtures" / "fake_claude.py")]


async def collect(conv, msg, schema=None):
    return [e async for e in conv.send(msg, schema)]


@pytest.fixture
def mode(monkeypatch):
    def set_mode(m):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", m)
    return set_mode


async def test_text_streams_and_multi_turn(mode, tmp_path, monkeypatch):
    mode("text")
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(tmp_path / "args.json"))
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("be helpful")
    ev1 = await collect(conv, Message("user", "hi", (b"\x89PNG fake",)))
    ev2 = await collect(conv, Message("user", "again"))
    assert "".join(e.text for e in ev1 if isinstance(e, Delta)) == "turn 1 images 1"
    assert next(e for e in ev2 if isinstance(e, Final)).text == "turn 2 images 0"
    usage = next(e for e in ev1 if isinstance(e, Usage))
    assert usage.model == "fake-model" and usage.cost_usd == 0.002
    args = json.loads((tmp_path / "args.json").read_text().splitlines()[0])
    for flag in ["-p", "--input-format", "stream-json", "--tools", "", "--strict-mcp-config",
                 "--no-session-persistence", "--setting-sources", "--system-prompt", "be helpful"]:
        assert flag in args
    await conv.close()


async def test_schema_result_parsed(mode):
    mode("schema")
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")
    ev = await collect(conv, Message("user", "explain"), schema={"type": "object"})
    final = next(e for e in ev if isinstance(e, Final))
    assert final.parsed["lines"][0]["translations"]["en"] == "test"
    assert not any(isinstance(e, Delta) for e in ev)
    await conv.close()


@pytest.mark.parametrize("m,kind", [("limit", "limit"), ("exit_auth", "auth"), ("garbage", "backend"),
                                    ("schema_missing", "schema")])
async def test_errors_classified(mode, m, kind):
    mode(m)
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")
    ev = await collect(conv, Message("user", "x"), schema={"type": "object"} if m == "schema_missing" else None)
    errs = [e for e in ev if isinstance(e, LLMError)]
    assert errs and errs[0].kind == kind
    await conv.close()


async def test_timeout_and_cancel(mode):
    mode("hang")
    conv = await ClaudeCLIBackend(FAKE, timeout_s=0.5).open("s")
    ev = await collect(conv, Message("user", "x"))
    assert ev[-1].kind == "timeout"
    conv2 = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")

    async def cancel_soon():
        await asyncio.sleep(0.5)
        await conv2.cancel()

    task = asyncio.create_task(cancel_soon())
    ev2 = await collect(conv2, Message("user", "x"))
    await task
    assert ev2[-1].kind == "cancelled"
    await conv.close(); await conv2.close()


async def test_early_aclose_does_not_leak_stale_output(mode):
    mode("text")
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")
    agen = conv.send(Message("user", "hi", (b"img",)))
    async for e in agen:
        if isinstance(e, Delta):
            break
    await agen.aclose()
    ev = await collect(conv, Message("user", "again"))
    assert next(e for e in ev if isinstance(e, Final)).text == "turn 1 images 0"
    await conv.close()


async def test_missing_executable_is_backend_error():
    conv = await ClaudeCLIBackend(["/nonexistent/claude"], timeout_s=5).open("s")
    ev = await collect(conv, Message("user", "x"))
    assert ev[-1].kind == "backend"
    await conv.close()


async def test_schema_change_restarts_process(mode, tmp_path, monkeypatch):
    mode("text")
    args_file = tmp_path / "args.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(args_file))
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")
    await collect(conv, Message("user", "a"))
    await collect(conv, Message("user", "b"), schema={"type": "object"})
    spawns = [json.loads(line) for line in args_file.read_text().splitlines()]
    assert len(spawns) == 2
    assert "--json-schema" not in spawns[0] and "--json-schema" in spawns[1]
    await conv.close()


async def test_timeout_kills_process(mode):
    mode("hang")
    conv = await ClaudeCLIBackend(FAKE, timeout_s=0.5).open("s")
    proc_holder = []
    orig = conv._ensure

    async def spy(schema):
        proc = await orig(schema)
        proc_holder.append(proc)
        return proc

    conv._ensure = spy
    ev = await collect(conv, Message("user", "x"))
    assert ev[-1].kind == "timeout"
    assert proc_holder[0].returncode is not None
    await conv.close()


async def test_progress_started_once_per_turn(mode):
    mode("text")
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")
    for _ in range(2):
        ev = await collect(conv, Message("user", "hi"))
        assert ev[0] == Progress("started")
        assert sum(1 for e in ev if e == Progress("started")) == 1
    await conv.close()


@pytest.mark.parametrize("m,schema", [("stream_text", None), ("stream_schema", {"type": "object"})])
async def test_progress_receiving_is_throttled(mode, m, schema):
    mode(m)
    conv = await ClaudeCLIBackend(FAKE, timeout_s=10).open("s")
    ev = await collect(conv, Message("user", "go"), schema)
    rec = [e for e in ev if isinstance(e, Progress) and e.stage == "receiving"]
    assert 2 <= len(rec) <= 6  # 12 pieces over ~1.2 s, at most one update per 0.3 s
    chars = [e.chars for e in rec]
    assert chars == sorted(chars) and chars[0] == 5 and chars[-1] > chars[0]
    assert any(isinstance(e, Final) for e in ev)
    await conv.close()


async def test_model_and_thinking_changes_respawn_with_new_flags(mode, tmp_path, monkeypatch):
    mode("text")
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(tmp_path / "args.json"))
    monkeypatch.setenv("FAKE_CLAUDE_ENV", str(tmp_path / "env.txt"))
    backend = ClaudeCLIBackend(FAKE, model="opus", timeout_s=10, thinking="low")
    conv = await backend.open("s")
    await collect(conv, Message("user", "a"))
    await collect(conv, Message("user", "b"))  # same choice: same process
    backend.model, backend.thinking = "sonnet", "off"
    await collect(conv, Message("user", "c"))
    await conv.close()
    spawns = [json.loads(line) for line in (tmp_path / "args.json").read_text().splitlines()]
    assert len(spawns) == 2
    first, second = spawns
    assert first[first.index("--model") + 1] == "opus" and first[first.index("--effort") + 1] == "low"
    assert second[second.index("--model") + 1] == "sonnet" and "--effort" not in second
    assert (tmp_path / "env.txt").read_text().splitlines() == ["-", "0"]
