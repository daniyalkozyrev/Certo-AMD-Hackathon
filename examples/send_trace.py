"""Certo SDK quickstart — send one trace and watch it get scored.

Sends a small 3-span trajectory to a running Certo backend, then polls until the
judge has graded it. Open the printed URL to see per-span scores in the UI.

Setup:
    pip install httpx            # the SDK's only dependency
    # from the repo root, `sdk/` must be importable (or `pip install -e sdk`)

Run:
    export CERTO_URL=http://localhost:8000
    export CERTO_API_KEY=certo_sk_...   # mint one: POST /api/v1/api-keys (or use a login JWT)
    python examples/send_trace.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk"))
import certo  # noqa: E402

BASE_URL = os.environ.get("CERTO_URL", "http://localhost:8000")
API_KEY = os.environ.get("CERTO_API_KEY", "")
if not API_KEY:
    sys.exit("Set CERTO_API_KEY (a certo_sk_… machine key, or a login JWT).")


# A real tool: @certo.tool records the ACTUAL call — args, result, latency —
# as a span. The model/agent never writes its own trace.
@certo.tool
def seconds_in(days: int) -> int:
    return days * 86400


with certo.trace(
    "How many seconds are in 3 days? Use a tool, then answer.",
    api_key=API_KEY,
    base_url=BASE_URL,
    name="sdk quickstart",
    expected_output="259200",  # ground truth -> objective axis
) as t:
    t.log_span("llm", "planner", input="plan the solution", output="call seconds_in(3)")
    result = seconds_in(3)
    t.finish(f"FINAL ANSWER: {result}")

trace_id = t.result["id"]
print(f"Trace {trace_id} submitted — waiting for the judge…")

with httpx.Client(timeout=30) as client:
    for _ in range(60):
        d = client.get(
            f"{BASE_URL}/api/v1/traces/{trace_id}",
            headers={"Authorization": f"Bearer {API_KEY}"},
        ).json()
        if d["status"] in ("completed", "failed"):
            break
        time.sleep(2)

print(f"status={d['status']}  TrustScore={d.get('trust_score')}")
for span in d.get("spans", []):
    print(f"  span {span['step_index']} ({span['kind']}:{span.get('name')}) -> "
          f"{span.get('judge_score')}/5")
print(f"Open {BASE_URL.replace('8000', '3000')}/traces/{trace_id} to see the full report.")
