#!/usr/bin/env python3
"""
Hermes -> Certo adapter  (zero dependencies, stdlib only).

Makes the locally-installed **Hermes Agent** look like an OpenAI-compatible
chat endpoint, so Certo can evaluate it as a normal one-shot agent — AND
exposes Hermes's real execution trajectory so Certo's judge can grade every
step, not just the final answer.

Flow:
    Certo  --POST /v1/chat/completions-->  this adapter
    adapter  --`hermes -z "<task>"`-->  Hermes (runs its tools, returns answer)
    adapter  --reads Hermes state.db-->  the run's trajectory (tool calls)
    adapter  --answer + <certo:trace> JSON-->  Certo (judge grades answer + steps)

We pass ONLY the user's task to Hermes (we ignore Certo's built-in "you are a
coding agent" system prompt) so Hermes answers the task as itself.

── Run it (in the SAME PowerShell where `hermes` works) ──────────────────────
    python C:\\Users\\user\\Desktop\\Certo\\adapters\\hermes_adapter.py

── Then in Certo -> New Evaluation -> Create new ────────────────────────────
    Type     = One-shot
    Base URL = http://localhost:8765/v1
    API key  = hermes          (any non-empty string; if empty, Certo uses a mock!)
    Model    = hermes          (just a label; Hermes uses its own configured model)
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Hermes answers can contain non-ASCII (→, ≈, …). The Windows console is cp1251 and
# raises UnicodeEncodeError on print() — which, inside the request handler, aborts
# the HTTP response and hangs the task. Force UTF-8 with replacement so a log line
# can never break the response.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST = "127.0.0.1"
PORT = 8765
HERMES = shutil.which("hermes") or "hermes"
TIMEOUT = 600  # seconds Hermes may spend per task (matches backend agent timeout)

# Prepended to every task so Hermes (a) uses its OWN tools instead of delegating to
# a subagent (which returns "I'll report back" before finishing), and (b) ends with
# the GAIA-style "FINAL ANSWER:" line that Certo's MATCH grader extracts.
GUIDANCE = (
    "Answer the question below. It may require looking things up — use your OWN "
    "tools directly (web_search, web_extract, browser, file read). Do NOT delegate "
    "to a subagent and do NOT use delegate_task; do the work yourself and wait for "
    "the result. Reason briefly, then finish with a single final line, exactly:\n"
    "FINAL ANSWER: <your answer>\n"
    "The final answer must be a number, OR as few words as possible, OR a "
    "comma-separated list. Give your single best guess if unsure.\n\nQUESTION:\n"
)

# --yolo prevents a headless run from hanging on an approval prompt.
# It also lets Hermes run commands without asking — remove it if you'd rather
# the agent never auto-run anything (at the risk of the run hanging).
EXTRA_ARGS = ["--yolo"]


# Hermes persists every run (messages + tool calls) here; we read it AFTER the
# subprocess exits to reconstruct the trajectory Certo's judge will grade.
STATE_DB = os.path.expandvars(r"%LOCALAPPDATA%\hermes\state.db")
TRACE_OPEN, TRACE_CLOSE = "<certo:trace>", "</certo:trace>"
MAX_SPANS = 20          # keep the trace (and judge cost) bounded
FIELD_LIMIT = 900       # chars per span input/output


def _clip(text: str | None, limit: int = FIELD_LIMIT) -> str:
    text = (text or "").strip()
    return text[:limit] + (" …[truncated]" if len(text) > limit else "")


def read_trajectory(started_after: float) -> list[dict]:
    """Best-effort: pull the tool-call spans of the Hermes session that our
    subprocess just created. Read-only; any failure just means 'no trace'."""
    try:
        db = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        row = db.execute(
            "SELECT id FROM sessions WHERE started_at >= ? ORDER BY started_at DESC LIMIT 1",
            (started_after - 5,),
        ).fetchone()
        if not row:
            return []
        msgs = db.execute(
            "SELECT role, content, tool_calls, tool_name, tool_call_id "
            "FROM messages WHERE session_id=? ORDER BY rowid",
            (row[0],),
        ).fetchall()
        db.close()
    except Exception as exc:
        print(f"[adapter] trace read failed: {exc}", file=sys.stderr)
        return []

    # Pair each assistant tool_call with the tool message that answered it.
    outputs: dict[str, str] = {}
    for role, content, _tc, _tn, tcid in msgs:
        if role == "tool" and tcid:
            out = content or ""
            try:  # hermes tool results are JSON like {"status":..., "output":...}
                parsed = json.loads(out)
                out = parsed.get("output") or parsed.get("content") or out
            except (json.JSONDecodeError, AttributeError):
                pass
            outputs[tcid] = out

    spans: list[dict] = []
    for role, content, tc_json, _tn, _tcid in msgs:
        if role != "assistant":
            continue
        thought = (content or "").strip()
        for tc in json.loads(tc_json) if tc_json else []:
            fn = tc.get("function") or {}
            spans.append({
                "kind": "tool",
                "name": fn.get("name") or "tool",
                "input": _clip(fn.get("arguments")),
                "output": _clip(outputs.get(tc.get("id") or tc.get("call_id") or "")),
                "thought": _clip(thought, 400) or None,
            })
            thought = ""  # attach the thought only to the first call it precedes
    return spans[:MAX_SPANS]


def run_hermes(task: str) -> tuple[str, list[dict]]:
    """Run one Hermes task; return (final answer, trajectory spans)."""
    cmd = [HERMES, "-z", task, *EXTRA_ARGS]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return "[adapter] 'hermes' not found. Run this from the terminal where `hermes` works.", []
    except subprocess.TimeoutExpired:
        return f"[adapter] Hermes timed out after {TIMEOUT}s.", []
    out = (proc.stdout or "").strip()
    if not out:
        err = (proc.stderr or "").strip()
        msg = f"[adapter] Hermes produced no stdout. stderr:\n{err[:1000]}" if err else "[adapter] (empty)"
        return msg, []
    return out, read_trajectory(t0)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        p = self.path.rstrip("/")
        if p in ("", "/v1", "/health"):
            self._json(200, {"status": "ok", "hermes": HERMES})
        elif p == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "hermes", "object": "model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        # The task is the last user message; ignore Certo's system prompt.
        task = ""
        for m in body.get("messages", []):
            if m.get("role") == "user" and m.get("content"):
                task = m["content"]
        print(f"[adapter] -> task: {task[:120]!r}", flush=True)
        answer, spans = run_hermes(GUIDANCE + task)
        print(f"[adapter] <- answer: {answer[:120]!r}  (+{len(spans)} trace spans)", flush=True)
        if spans:
            # Certo strips this block from the answer and grades each span.
            answer += f"\n\n{TRACE_OPEN}\n{json.dumps(spans, ensure_ascii=False)}\n{TRACE_CLOSE}"

        self._json(200, {
            "id": "chatcmpl-hermes",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "hermes"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def log_message(self, *a) -> None:  # silence default request logging
        pass


if __name__ == "__main__":
    if shutil.which("hermes") is None:
        print(
            "WARNING: 'hermes' is not on PATH in this shell. Start this adapter from\n"
            "the same PowerShell where the `hermes` command works.",
            file=sys.stderr,
        )
    print(f"Hermes->Certo adapter listening on http://{HOST}:{PORT}/v1   (hermes={HERMES})")
    print("In Certo set Base URL = http://localhost:8765/v1  (API key = any non-empty string)")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nadapter stopped.")
