"""Stand-in for `claude -p --input-format stream-json --output-format stream-json`."""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "text")
args_file = os.environ.get("FAKE_CLAUDE_ARGS")
if args_file:
    with open(args_file, "a") as f:  # one JSON line per spawn
        f.write(json.dumps(sys.argv[1:]) + "\n")


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if mode == "exit_auth":
    sys.stderr.write("Invalid API key · Please run /login\n")
    sys.exit(1)

out({"type": "system", "subtype": "init", "model": "fake-model"})
turn = 0
for line in sys.stdin:
    msg = json.loads(line)
    turn += 1
    content = msg["message"]["content"]
    n_images = sum(1 for c in content if c["type"] == "image")
    if mode == "hang":
        time.sleep(60)
    if mode == "garbage":
        sys.stdout.write("this is not json\n"); sys.stdout.flush()
        sys.exit(3)
    if mode == "limit":
        out({"type": "result", "subtype": "success", "is_error": True, "result": "Claude usage limit reached",
             "duration_ms": 5})
        continue
    if mode == "schema":
        out({"type": "result", "subtype": "success", "is_error": False, "result": "{}", "duration_ms": 12,
             "structured_output": {"lines": [{"source": "テスト", "reading": "てすと",
                                              "translations": {"en": "test"}, "note": ""}],
                                   "words": [], "summary": ""},
             "total_cost_usd": 0.01, "usage": {"input_tokens": 5, "output_tokens": 7},
             "modelUsage": {"fake-model": {}}})
        continue
    if mode in ("stream_text", "stream_schema"):
        # 12 pieces of 5 chars, 0.1 s apart: a throttled Progress stream must be much sparser than the pieces
        for i in range(12):
            if mode == "stream_text":
                delta = {"type": "text_delta", "text": "abcde"}
            else:
                delta = {"type": "input_json_delta", "partial_json": "abcde"}
            out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": delta}})
            time.sleep(0.1)
        res = {"type": "result", "subtype": "success", "is_error": False, "result": "abcde" * 12, "duration_ms": 1,
               "modelUsage": {"fake-model": {}}}
        if mode == "stream_schema":
            res["structured_output"] = {"ok": True}
        out(res)
        continue
    if mode == "schema_missing":
        out({"type": "result", "subtype": "success", "is_error": False, "result": "plain words", "duration_ms": 3})
        continue
    text = f"turn {turn} images {n_images}"
    for piece in (text[:5], text[5:]):
        out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                "delta": {"type": "text_delta", "text": piece}}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": text, "duration_ms": 20,
         "total_cost_usd": 0.002, "usage": {"input_tokens": 3, "output_tokens": 4}, "modelUsage": {"fake-model": {}}})
