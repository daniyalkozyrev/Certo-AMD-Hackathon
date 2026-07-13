"""Compare agent models by TrustScore — with variance, so a gap isn't mistaken for noise.

Runs a benchmark N times per agent against the live backend, collects the N
TrustScores, and prints a markdown report: per-model mean +/- std and a 95% CI,
plus a ranked table that only calls "A > B" when their CIs do not overlap.

    cd backend && .venv/Scripts/python -m scripts.compare_models \
        --agents <agent_id_1>,<agent_id_2> --benchmark <suite_id> --runs 5

Auth: uses the ENV=local dev-code login (same as the demo). A stochastic agent +
an LLM judge make a single run unreliable; N>=5 is the point of this tool.
"""

from __future__ import annotations

import argparse
import math
import statistics
import time

import httpx

EMAIL = "daniyalkozyrev@gmail.com"


def _login(client: httpx.Client, api: str) -> str:
    code = client.post(f"{api}/auth/request-code", json={"email": EMAIL}).json().get("dev_code")
    if not code:
        raise SystemExit("No dev_code returned (ENV=local + expose_dev_code required).")
    verified = client.post(f"{api}/auth/verify", json={"email": EMAIL, "code": code}).json()
    return verified["access_token"]


def _run_once(client: httpx.Client, api: str, hdr: dict, agent_id: str, benchmark_id: str,
              poll_s: int = 5, max_wait_s: int = 3600) -> dict | None:
    eid = client.post(f"{api}/evaluations",
                      json={"agent_id": agent_id, "benchmark_id": benchmark_id},
                      headers=hdr).json()["id"]
    waited = 0
    while waited < max_wait_s:
        d = client.get(f"{api}/evaluations/{eid}", headers=hdr).json()
        if d["status"] in ("completed", "failed"):
            return d if d["status"] == "completed" else None
        time.sleep(poll_s)
        waited += poll_s
    return None


def _ci95(xs: list[float]) -> tuple[float, float, float]:
    """Return (mean, std, half-width of a ~95% CI). Normal approx; rough for small N."""
    n = len(xs)
    mean = statistics.fmean(xs)
    std = statistics.stdev(xs) if n > 1 else 0.0
    half = 1.96 * std / math.sqrt(n) if n > 1 else 0.0
    return mean, std, half


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", required=True, help="comma-separated agent ids")
    ap.add_argument("--benchmark", required=True, help="benchmark id (e.g. the Certo Agent Suite)")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    api = f"{args.base_url.rstrip('/')}/api/v1"
    agent_ids = [a.strip() for a in args.agents.split(",") if a.strip()]

    with httpx.Client(timeout=60) as client:
        hdr = {"Authorization": f"Bearer {_login(client, api)}"}
        names = {}
        results: dict[str, list[dict]] = {}
        for aid in agent_ids:
            try:
                names[aid] = client.get(f"{api}/agents/{aid}", headers=hdr).json().get("name", aid)
            except Exception:
                names[aid] = aid
            results[aid] = []
            for r in range(args.runs):
                print(f"[{names[aid]}] run {r + 1}/{args.runs} ...", flush=True)
                d = _run_once(client, api, hdr, aid, args.benchmark)
                if d is not None:
                    results[aid].append(d)
                    print(f"    trust={d.get('trust_score')} pass_rate={d.get('pass_rate')}")
                else:
                    print("    run failed/timeout — skipped")

    # ── report ────────────────────────────────────────────────────────────
    rows = []
    for aid in agent_ids:
        scores = [d["trust_score"] for d in results[aid] if d.get("trust_score") is not None]
        if not scores:
            rows.append((names[aid], 0.0, 0.0, 0.0, 0, []))
            continue
        mean, std, half = _ci95(scores)
        rows.append((names[aid], mean, std, half, len(scores), scores))
    rows.sort(key=lambda r: r[1], reverse=True)

    print("\n## Model comparison — TrustScore (mean ± std over N runs)\n")
    print("| rank | model | runs | mean | std | 95% CI |")
    print("|---:|---|---:|---:|---:|---|")
    for i, (name, mean, std, half, n, _) in enumerate(rows, 1):
        ci = f"[{mean - half:.1f}, {mean + half:.1f}]" if n > 1 else "n/a"
        print(f"| {i} | {name} | {n} | {mean:.1f} | {std:.1f} | {ci} |")

    # significance note: CIs overlapping -> difference not established
    print("\n### Is the ranking real?")
    if len(rows) >= 2 and rows[0][4] > 1 and rows[1][4] > 1:
        (_, m0, _, h0, _, _), (_, m1, _, h1, _, _) = rows[0], rows[1]
        overlap = (m0 - h0) <= (m1 + h1)
        verdict = ("NOT significant — the top-2 confidence intervals overlap; run more iterations "
                   "or add tasks before claiming a winner." if overlap else
                   "significant — the top-2 confidence intervals are separated.")
        print(f"- Top-2 gap is **{verdict}**")
    else:
        print("- Need >=2 runs per model (use --runs) to judge significance.")


if __name__ == "__main__":
    main()
